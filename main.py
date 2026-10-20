"""
main.py
Command-line driver for the MEDSAFE-DSL compiler and virtual machine.

Phase 1 (front-end):
    source (.smed) -> Lexer -> Parser -> AST -> SemanticAnalyzer
Phase 2 (back-end):
    verified AST -> IRGenerator -> Optimizer -> bytecode.assemble (.medc)
Phase 3 (execution):
    bytecode -> MedsafeVM.load (re-verify) -> discrete-event simulation with a
    runtime safety monitor.

Usage examples
    python main.py phase3_demo.smed                 # full pipeline + VM run
    python main.py phase3_demo.smed --trace         # print the simulation trace
    python main.py phase3_demo.smed --perf          # timing / memory / optimizer stats
    python main.py phase3_demo.smed --emit-bytecode out.medc
    python main.py --exec out.medc                  # run precompiled bytecode (no source)
"""
import argparse
import sys
import time
import tracemalloc

from lexer import Lexer, LexicalError
from parser import Parser, SyntaxErrorMEDSAFE
from semantic import SemanticAnalyzer, SemanticError, ReferenceError_
from symbol_table import SymbolCollisionError
from ir import IRGenerator
from optimizer import Optimizer
import bytecode
from vm import MedsafeVM, VMError, format_trace


def _print_ir(title: str, instrs) -> None:
    print(f"\n[{title}] ({len(instrs)} instructions)")
    for instr in instrs:
        print("  " + instr.text())


def _report_simulation(result, show_trace: bool) -> None:
    print(f"\n[Simulation] horizon {result.horizon_hr:g} hr, {len(result.segments)} event intervals, "
          f"{result.instructions_executed} instructions executed")
    if show_trace:
        print(format_trace(result))
    for (patient, drug), mg in sorted(result.cumulative.items()):
        peak = result.peak_rate.get((patient, drug), 0.0)
        print(f"  {patient}/{drug}: cumulative {mg:.3f} mg, peak concurrent rate {peak:.3f} mg/hr")
    if result.alarms:
        print(f"\n[Runtime Monitor] {len(result.alarms)} ALARM(S):")
        for al in result.alarms:
            print(f"  ! {al.kind}: {al.message}")
    else:
        print("\n[Runtime Monitor] no alarms -- protocol stayed within every limit")


def exec_bytecode(path: str, horizon: float | None, show_trace: bool, strict: bool) -> int:
    try:
        with open(path, "rb") as f:
            instrs = bytecode.disassemble(f.read())
        result = MedsafeVM(instrs, horizon).run()
    except (bytecode.BytecodeError, VMError) as e:
        print(f"[VM Error] {e}")
        return 1
    print(f"BYTECODE LOADED        OK  ({len(instrs)} instructions)")
    print("VM LOAD VERIFICATION   OK")
    _report_simulation(result, show_trace)
    return 2 if (strict and result.alarms) else 0


def run(path: str, show_tokens: bool, show_ast: bool, show_symtab: bool,
        show_ir: bool, show_optimized: bool, show_bytecode: bool,
        bytecode_out: str | None, show_trace: bool = False, show_perf: bool = False,
        horizon: float | None = None, strict: bool = False,
        quiet_stages: bool = False) -> int:
    any_inspection = (show_tokens or show_ast or show_symtab or show_ir or
                      show_optimized or show_bytecode or show_trace or show_perf)
    stage_mode = not any_inspection and not quiet_stages
    timings: dict[str, float] = {}

    def timed(name, fn):
        t0 = time.perf_counter()
        out = fn()
        timings[name] = time.perf_counter() - t0
        return out

    if show_perf:
        tracemalloc.start()

    with open(path, "r") as f:
        source = f.read()

    try:
        tokens = timed("lexing", lambda: Lexer(source).tokenize())
    except LexicalError as e:
        print(e)
        return 1
    if stage_mode:
        print("LEXICAL ANALYSIS       OK")
    if show_tokens:
        for t in tokens:
            print(t)

    try:
        program = timed("parsing", lambda: Parser(tokens).parse_program())
    except SyntaxErrorMEDSAFE as e:
        print(e)
        return 1
    if stage_mode:
        print("SYNTAX ANALYSIS        OK")
        print("AST CONSTRUCTION       OK")
    if show_ast:
        print(program.pretty())

    try:
        analyzer = SemanticAnalyzer(program)
        symtab = timed("semantic analysis", analyzer.analyze)
    except (SymbolCollisionError, ReferenceError_, SemanticError) as e:
        print(e)
        return 1
    if stage_mode:
        print("SYMBOL TABLE           OK")
        print("SEMANTIC ANALYSIS      OK")

    if show_symtab:
        print(f"{'NAME':<12}{'KIND':<10}{'TYPE':<28}{'BASELINE':<10}{'LINE:COL'}")
        for entry in symtab.all_entries():
            print(f"{entry.name:<12}{entry.kind:<10}{entry.inferred_type:<28}"
                  f"{entry.baseline_value:<10}{entry.declared_at[0]}:{entry.declared_at[1]}")

    if stage_mode:
        print("DOMAIN STATIC ANALYSIS OK  (rate + concurrent same-drug + cumulative + interaction)")

    print(f"\n[Diagnostic Report] {len(analyzer.checks)} rate check(s) statically verified:")
    for c in analyzer.checks:
        extra = ""
        if c.kind == "conditional":
            extra = f"  [{c.detail['condition']} -> {c.detail['branch']}]"
        elif c.kind == "repeat":
            extra = (f"  [x{c.detail['repeat_count']} over {c.detail['until_hr']:.0f}hr, "
                     f"{c.detail['total_mg']:.1f} mg total]")
        print(f"  {c.kind.upper():<11} {c.subject}: {c.rate_mg_per_hr:.3f} mg/hr <= "
              f"{c.limit_mg_per_hr:.3f} mg/hr  -> {c.verdict}{extra}")
    for cc in analyzer.concurrency_checks:
        print(f"  CONCURRENT  {cc.patient}/{cc.drug}: peak {cc.peak_mg_per_hr:.3f} mg/hr at "
              f"t={cc.peak_time_hr:g}hr <= {cc.limit_mg_per_hr:.3f} mg/hr "
              f"(sources: {', '.join(cc.sources)})  -> {cc.verdict}")
    for t in analyzer.total_checks:
        print(f"  CUMULATIVE  {t.patient}/{t.drug}: {t.total_mg:.3f} mg <= {t.limit_mg:.3f} mg "
              f"(MAX_TOTAL, schedules: {', '.join(t.contributors)})  -> {t.verdict}")
    for ic in analyzer.interaction_checks:
        print(f"  INTERACTION {ic.patient}/{ic.drug_a}+{ic.drug_b}: {ic.combined_mg_per_hr:.3f} mg/hr <= "
              f"{ic.limit_mg_per_hr:.3f} mg/hr  -> {ic.verdict}")

    # ---- Phase 2: IR generation, optimization, bytecode ----------------
    naive_ir = timed("IR generation", lambda: IRGenerator(
        program, symtab, analyzer.checks, analyzer.total_checks,
        analyzer.interaction_checks).generate())
    if stage_mode:
        print("IR GENERATION          OK")
    if show_ir:
        _print_ir("Intermediate Representation (naive)", naive_ir)

    optimized_ir, opt_report = timed("optimization", lambda: Optimizer(naive_ir).optimize())
    if stage_mode:
        print(f"OPTIMIZATION           OK  ({opt_report.original_count} -> "
              f"{opt_report.optimized_count} instructions, {opt_report.eliminated} eliminated)")
    if show_optimized:
        _print_ir("Optimized Intermediate Representation", optimized_ir)
        for note in opt_report.notes:
            print(f"  * {note}")

    code = timed("bytecode generation", lambda: bytecode.assemble(optimized_ir))
    if stage_mode:
        print(f"BYTECODE GENERATION    OK  ({len(code)} bytes)")
    if show_bytecode:
        print(f"\n[Bytecode] {len(code)} bytes, magic={code[:4]!r}")
        _print_ir("Disassembled Bytecode", bytecode.disassemble(code))
    if bytecode_out:
        with open(bytecode_out, "wb") as f:
            f.write(code)
        print(f"\nBytecode written to {bytecode_out}")

    # ---- Phase 3: execute on the VM -------------------------------------
    try:
        vm = MedsafeVM(bytecode.disassemble(code), horizon)
        t0 = time.perf_counter()
        vm.load()
        timings["VM load + verify"] = time.perf_counter() - t0
        result = timed("VM simulation", vm.simulate)
    except VMError as e:
        print(f"[VM Error] {e}")
        return 1
    if stage_mode:
        print("VM LOAD VERIFICATION   OK  (every CHECK_* instruction re-verified)")
        print(f"SIMULATION             {result.status}  ({len(result.segments)} event intervals, "
              f"{len(result.alarms)} alarm(s))")
    _report_simulation(result, show_trace)

    if show_perf:
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        print("\n[Performance]")
        for name, secs in timings.items():
            print(f"  {name:<22} {secs * 1000:9.3f} ms")
        print(f"  {'TOTAL':<22} {sum(timings.values()) * 1000:9.3f} ms")
        print(f"  peak memory            {peak / 1024:9.1f} KiB")
        print(f"  source size            {len(source):9d} bytes")
        print(f"  bytecode size          {len(code):9d} bytes")
        pct = 100.0 * opt_report.eliminated / max(1, opt_report.original_count)
        print(f"  optimizer              {opt_report.original_count} -> {opt_report.optimized_count} "
              f"instructions ({pct:.1f}% eliminated)")

    if stage_mode:
        print("COMPILATION SUCCESSFUL" + ("  (with runtime alarms)" if result.alarms else ""))
    else:
        print("\nCompilation successful. No static safety violations detected.")
    return 2 if (strict and result.alarms) else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(prog="main.py", description="MEDSAFE-DSL compiler and VM")
    parser.add_argument("source", nargs="?", help="path to a .smed source file")
    parser.add_argument("--tokens", action="store_true", help="print the lexical token stream")
    parser.add_argument("--ast", action="store_true", help="print the parsed AST")
    parser.add_argument("--symtab", action="store_true", help="print the resolved symbol table")
    parser.add_argument("--ir", action="store_true", help="print the naive (pre-optimization) IR")
    parser.add_argument("--optimize", action="store_true", help="print the optimized IR and the optimization report")
    parser.add_argument("--bytecode", action="store_true", help="print the assembled bytecode and its disassembly")
    parser.add_argument("--emit-bytecode", metavar="FILE", help="write the assembled bytecode to FILE")
    parser.add_argument("--exec", metavar="FILE", dest="exec_file",
                        help="execute precompiled bytecode FILE on the VM (no source needed)")
    parser.add_argument("--trace", action="store_true", help="print the simulation event trace")
    parser.add_argument("--perf", action="store_true", help="print per-stage timing, memory and optimizer statistics")
    parser.add_argument("--horizon", type=float, metavar="HOURS", help="override the simulation horizon (hours)")
    parser.add_argument("--strict", action="store_true", help="exit with status 2 if the runtime monitor raises any alarm")
    args = parser.parse_args()

    if args.exec_file:
        sys.exit(exec_bytecode(args.exec_file, args.horizon, args.trace, args.strict))
    if not args.source:
        parser.error("a source file is required (or use --exec FILE.medc)")
    sys.exit(run(args.source, args.tokens, args.ast, args.symtab,
                 args.ir, args.optimize, args.bytecode, args.emit_bytecode,
                 args.trace, args.perf, args.horizon, args.strict))
