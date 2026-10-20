"""
benchmark.py
Reproducible performance evaluation of the MEDSAFE-DSL toolchain.

Generates synthetic protocols of increasing size (patients, continuous
infusions, REPEAT schedules, interactions), pushes each through every
compiler stage plus the VM, and prints wall-clock time per stage, peak memory,
bytecode size and the optimizer's instruction reduction.

    python benchmark.py            # default sizes
    python benchmark.py 50 500     # custom numbers of patients
"""
import sys
import time
import tracemalloc

import bytecode
from ir import IRGenerator
from lexer import Lexer
from optimizer import Optimizer
from parser import Parser
from semantic import SemanticAnalyzer
from vm import MedsafeVM


def synth_program(patients: int) -> str:
    """Each patient gets: 2 continuous infusions (one multi-drug), 1 REPEAT of
    6 administrations, and the program declares one interaction pair."""
    lines = [
        "DRUG dopamine { MAX_RATE: 50 mg/hr; MAX_TOTAL: 5000 mg; }",
        "DRUG heparin  { MAX_RATE: 30 mg/hr; }",
        "DRUG morphine { MAX_RATE: 10 mg/hr; MAX_TOTAL: 500 mg; }",
        "INTERACTION dopamine WITH heparin LIMIT 70 mg/hr;",
    ]
    for i in range(patients):
        lines.append(f"PATIENT p{i} {{ WEIGHT: {40 + i % 60} kg; }}")
    for i in range(patients):
        lines.append(f"INFUSION c{i} FOR p{i} USING dopamine AT 8 mg/hr, heparin AT 5 mg/hr;")
        lines.append(f"INFUSION t{i} FOR p{i} USING morphine IF WEIGHT >= 60 kg THEN 3 mg/hr ELSE 2 mg/hr;")
        lines.append(f"REPEAT r{i} FOR p{i} USING morphine AT 2 mg/hr EVERY 4 hr UNTIL 24 hr OVER 1 hr;")
    return "\n".join(lines) + "\n"


def run_once(patients: int, measure_memory: bool) -> dict:
    source = synth_program(patients)
    stages: dict[str, float] = {}

    def timed(name, fn):
        t0 = time.perf_counter()
        out = fn()
        stages[name] = time.perf_counter() - t0
        return out

    if measure_memory:
        tracemalloc.start()
    tokens = timed("lex", lambda: Lexer(source).tokenize())
    program = timed("parse", lambda: Parser(tokens).parse_program())
    analyzer = SemanticAnalyzer(program)
    symtab = timed("semantic", analyzer.analyze)
    naive = timed("ir", lambda: IRGenerator(program, symtab, analyzer.checks,
                                            analyzer.total_checks, analyzer.interaction_checks).generate())
    optimized, report = timed("optimize", lambda: Optimizer(naive).optimize())
    code = timed("bytecode", lambda: bytecode.assemble(optimized))
    vm = MedsafeVM(bytecode.disassemble(code))
    timed("vm load", vm.load)
    result = timed("vm simulate", vm.simulate)
    peak = 0
    if measure_memory:
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
    return {
        "patients": patients, "decl_lines": source.count("\n"), "tokens": len(tokens),
        "naive_ir": report.original_count, "opt_ir": report.optimized_count,
        "bytes": len(code), "events": len(result.segments), "alarms": len(result.alarms),
        "peak_kib": peak / 1024, "stages": stages, "total_ms": sum(stages.values()) * 1000,
    }


def main(sizes):
    # Two passes: tracemalloc slows execution several-fold, so timing is measured
    # with it OFF and memory is measured in a separate pass with it ON.
    mem = {n: run_once(n, True)["peak_kib"] for n in sizes}
    rows = [dict(run_once(n, False), peak_kib=mem[n]) for n in sizes]
    print(f"{'patients':>8} {'lines':>6} {'tokens':>7} {'naiveIR':>8} {'optIR':>6} {'-%':>5} "
          f"{'bytes':>8} {'events':>7} {'total ms':>9} {'peak KiB':>9}")
    for r in rows:
        cut = 100.0 * (r["naive_ir"] - r["opt_ir"]) / r["naive_ir"]
        print(f"{r['patients']:>8} {r['decl_lines']:>6} {r['tokens']:>7} {r['naive_ir']:>8} {r['opt_ir']:>6} "
              f"{cut:>5.1f} {r['bytes']:>8} {r['events']:>7} {r['total_ms']:>9.2f} {r['peak_kib']:>9.1f}")
    print("\nper-stage time (ms) for the largest program:")
    for name, secs in rows[-1]["stages"].items():
        print(f"  {name:<12} {secs * 1000:9.2f}")


if __name__ == "__main__":
    main([int(a) for a in sys.argv[1:]] or [10, 100, 500, 1000])
