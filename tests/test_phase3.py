import contextlib
import io
import os
import sys
import tempfile
import unittest

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, ROOT)

import bytecode
import main as medsafe_main
from ir import IRGenerator
from lexer import Lexer
from optimizer import Optimizer
from parser import Parser, SyntaxErrorMEDSAFE
from semantic import SemanticAnalyzer, SemanticError, ReferenceError_
from vm import MedsafeVM, VMError

HEAD = """
PATIENT p1 { WEIGHT: 70 kg; }
PATIENT p2 { WEIGHT: 30 kg; }
DRUG dopamine { MAX_RATE: 20 mg/hr; MAX_TOTAL: 100 mg; }
DRUG heparin { MAX_RATE: 15 mg/hr; }
"""


def parse(src):
    return Parser(Lexer(src).tokenize()).parse_program()


def analyze(src):
    program = parse(src)
    analyzer = SemanticAnalyzer(program)
    symtab = analyzer.analyze()
    return program, symtab, analyzer


def compile_to_instrs(src, optimize=True):
    program, symtab, a = analyze(src)
    ir = IRGenerator(program, symtab, a.checks, a.total_checks, a.interaction_checks).generate()
    return Optimizer(ir).optimize()[0] if optimize else ir


def read_demo(name):
    with open(os.path.join(ROOT, name)) as f:
        return f.read()


def run_vm(src, horizon=None):
    """Compile -> assemble -> disassemble -> VM, exactly like the CLI does."""
    code = bytecode.assemble(compile_to_instrs(src))
    return MedsafeVM(bytecode.disassemble(code), horizon).run(), code


# ---------------------------------------------------------------- grammar
class TestPhase3Grammar(unittest.TestCase):
    def test_drug_without_max_total_still_parses(self):
        d = parse("DRUG heparin { MAX_RATE: 15 mg/hr; }").drugs[0]
        self.assertIsNone(d.max_total)

    def test_drug_with_max_total_parses(self):
        d = parse("DRUG dopamine { MAX_RATE: 20 mg/hr; MAX_TOTAL: 100 mg; }").drugs[0]
        self.assertEqual((d.max_total.value, d.max_total.unit), (100.0, "mg"))

    def test_max_total_missing_semicolon_is_syntax_error(self):
        with self.assertRaises(SyntaxErrorMEDSAFE):
            parse("DRUG d { MAX_RATE: 20 mg/hr; MAX_TOTAL: 100 mg }")

    def test_interaction_decl_parses(self):
        ix = parse("INTERACTION dopamine WITH heparin LIMIT 18 mg/hr;").interactions[0]
        self.assertEqual((ix.drug_a, ix.drug_b, ix.limit.value), ("dopamine", "heparin", 18.0))

    def test_interaction_missing_with_is_syntax_error(self):
        with self.assertRaises(SyntaxErrorMEDSAFE):
            parse("INTERACTION dopamine heparin LIMIT 18 mg/hr;")

    def test_repeat_over_clause_parses(self):
        r = parse(HEAD + "REPEAT r FOR p1 USING dopamine AT 5 mg/hr EVERY 4 hr UNTIL 24 hr OVER 1 hr;").repeats[0]
        self.assertEqual((r.duration.value, r.duration.unit), (1.0, "hr"))

    def test_repeat_without_over_has_no_duration(self):
        r = parse(HEAD + "REPEAT r FOR p1 USING dopamine AT 5 mg/hr EVERY 4 hr UNTIL 24 hr;").repeats[0]
        self.assertIsNone(r.duration)

    def test_phase3_keywords_are_reserved(self):
        with self.assertRaises(SyntaxErrorMEDSAFE):
            parse("PATIENT OVER { WEIGHT: 70 kg; }")


# ---------------------------------------------------------------- semantics
class TestCumulativeDose(unittest.TestCase):
    def test_total_is_rate_times_duration_times_count(self):
        _, _, a = analyze(HEAD + "REPEAT r FOR p1 USING dopamine AT 10 mg/hr EVERY 4 hr UNTIL 24 hr OVER 1 hr;")
        self.assertAlmostEqual(a.total_checks[0].total_mg, 60.0)  # 10 * 1 * 6

    def test_without_over_assumes_continuous(self):
        _, _, a = analyze("PATIENT p1 { WEIGHT: 70 kg; }\nDRUG d { MAX_RATE: 20 mg/hr; MAX_TOTAL: 500 mg; }\n"
                          "REPEAT r FOR p1 USING d AT 5 mg/hr EVERY 4 hr UNTIL 24 hr;")
        self.assertAlmostEqual(a.total_checks[0].total_mg, 120.0)  # 5 * 4 * 6

    def test_exceeding_max_total_raises(self):
        with self.assertRaises(SemanticError) as cm:
            analyze(HEAD + "REPEAT r FOR p1 USING dopamine AT 10 mg/hr EVERY 4 hr UNTIL 24 hr OVER 2 hr;")  # 120 > 100
        self.assertIn("MAX_TOTAL", str(cm.exception))

    def test_total_exactly_at_limit_is_allowed(self):
        _, _, a = analyze(HEAD + "REPEAT r FOR p1 USING dopamine AT 10 mg/hr EVERY 6 hr UNTIL 24 hr OVER 2.5 hr;")  # 100.0
        self.assertAlmostEqual(a.total_checks[0].total_mg, 100.0)

    def test_two_schedules_accumulate(self):
        with self.assertRaises(SemanticError):
            analyze(HEAD +
                    "REPEAT a FOR p1 USING dopamine AT 10 mg/hr EVERY 4 hr UNTIL 24 hr OVER 1 hr;\n"  # 60
                    "REPEAT b FOR p1 USING dopamine AT 10 mg/hr EVERY 4 hr UNTIL 24 hr OVER 1 hr;")   # +60 = 120

    def test_cumulative_is_tracked_per_patient(self):
        _, _, a = analyze(HEAD +
                          "REPEAT a FOR p1 USING dopamine AT 10 mg/hr EVERY 4 hr UNTIL 24 hr OVER 1 hr;\n"
                          "REPEAT b FOR p2 USING dopamine AT 10 mg/hr EVERY 4 hr UNTIL 24 hr OVER 1 hr;")
        self.assertEqual(len(a.total_checks), 2)

    def test_drug_without_max_total_has_no_total_check(self):
        _, _, a = analyze(HEAD + "REPEAT r FOR p1 USING heparin AT 5 mg/hr EVERY 4 hr UNTIL 24 hr;")
        self.assertEqual(a.total_checks, [])

    def test_over_longer_than_interval_raises(self):
        with self.assertRaises(SemanticError):
            analyze(HEAD + "REPEAT r FOR p1 USING dopamine AT 5 mg/hr EVERY 4 hr UNTIL 24 hr OVER 5 hr;")

    def test_over_equal_to_interval_is_allowed(self):
        analyze(HEAD + "REPEAT r FOR p1 USING heparin AT 5 mg/hr EVERY 4 hr UNTIL 24 hr OVER 4 hr;")

    def test_over_in_minutes_is_normalized(self):
        _, _, a = analyze(HEAD + "REPEAT r FOR p1 USING dopamine AT 10 mg/hr EVERY 4 hr UNTIL 24 hr OVER 30 min;")
        self.assertAlmostEqual(a.total_checks[0].total_mg, 30.0)  # 10 * 0.5 * 6

    def test_mcg_max_total_is_normalized(self):
        _, _, a = analyze("PATIENT p1 { WEIGHT: 70 kg; }\nDRUG d { MAX_RATE: 20 mg/hr; MAX_TOTAL: 100000 mcg; }\n"
                          "REPEAT r FOR p1 USING d AT 10 mg/hr EVERY 6 hr UNTIL 24 hr OVER 2 hr;")  # 80 mg vs 100 mg
        self.assertAlmostEqual(a.total_checks[0].limit_mg, 100.0)


class TestInteractions(unittest.TestCase):
    IX = "INTERACTION dopamine WITH heparin LIMIT 18 mg/hr;\n"

    def test_safe_combination_recorded(self):
        _, _, a = analyze(HEAD + self.IX + "INFUSION c FOR p1 USING dopamine AT 10 mg/hr, heparin AT 5 mg/hr;")
        self.assertAlmostEqual(a.interaction_checks[0].combined_mg_per_hr, 15.0)

    def test_unsafe_combination_raises_with_source_names(self):
        with self.assertRaises(SemanticError) as cm:
            analyze(HEAD + self.IX + "INFUSION c FOR p1 USING dopamine AT 12 mg/hr, heparin AT 8 mg/hr;")
        self.assertIn("c[dopamine]", str(cm.exception))

    def test_combined_exactly_at_limit_is_allowed(self):
        analyze(HEAD + self.IX + "INFUSION c FOR p1 USING dopamine AT 10 mg/hr, heparin AT 8 mg/hr;")

    def test_zero_limit_means_contraindicated(self):
        with self.assertRaises(SemanticError):
            analyze(HEAD + "INTERACTION dopamine WITH heparin LIMIT 0 mg/hr;\n"
                           "INFUSION c FOR p1 USING dopamine AT 1 mg/hr, heparin AT 1 mg/hr;")

    def test_interaction_across_separate_infusions_same_patient(self):
        with self.assertRaises(SemanticError):
            analyze(HEAD + self.IX +
                    "INFUSION a FOR p1 USING dopamine AT 12 mg/hr;\n"
                    "INFUSION b FOR p1 USING heparin AT 9 mg/hr;")

    def test_interaction_does_not_cross_patients(self):
        _, _, a = analyze(HEAD + self.IX +
                          "INFUSION a FOR p1 USING dopamine AT 15 mg/hr;\n"
                          "INFUSION b FOR p2 USING heparin AT 14 mg/hr;")
        self.assertEqual(a.interaction_checks, [])

    def test_interaction_with_unknown_drug_raises(self):
        with self.assertRaises(ReferenceError_):
            analyze(HEAD + "INTERACTION dopamine WITH warfarin LIMIT 10 mg/hr;")

    def test_interaction_of_drug_with_itself_raises(self):
        with self.assertRaises(SemanticError):
            analyze(HEAD + "INTERACTION dopamine WITH dopamine LIMIT 10 mg/hr;")

    def test_interaction_works_with_conditional_infusion(self):
        _, _, a = analyze(HEAD + self.IX +
                          "INFUSION a FOR p1 USING dopamine IF WEIGHT >= 50 kg THEN 10 mg/hr ELSE 4 mg/hr;\n"
                          "INFUSION b FOR p1 USING heparin AT 6 mg/hr;")
        self.assertAlmostEqual(a.interaction_checks[0].combined_mg_per_hr, 16.0)


# ---------------------------------------------------------------- IR / bytecode
class TestPhase3IRAndBytecode(unittest.TestCase):
    SRC = (HEAD + "INTERACTION dopamine WITH heparin LIMIT 30 mg/hr;\n"
           "INFUSION c FOR p1 USING dopamine AT 8 mg/hr, heparin AT 5 mg/hr;\n"
           "REPEAT r FOR p1 USING dopamine AT 10 mg/hr EVERY 6 hr UNTIL 24 hr OVER 1 hr;")

    def opcodes(self):
        return [i.opcode for i in compile_to_instrs(self.SRC)]

    def test_new_opcodes_are_emitted(self):
        ops = self.opcodes()
        for op in ("DEF_INTERACT", "INFUSE", "SCHEDULE", "CHECK_TOTAL", "CHECK_INTERACT", "HALT"):
            self.assertIn(op, ops)

    def test_one_infuse_per_continuous_binding(self):
        self.assertEqual(self.opcodes().count("INFUSE"), 2)

    def test_def_drug_carries_max_total(self):
        drug = next(i for i in compile_to_instrs(self.SRC) if i.opcode == "DEF_DRUG" and i.operands["name"] == "dopamine")
        self.assertEqual(drug.operands["max_total"], "100.0mg")

    def test_roundtrip_with_phase3_opcodes(self):
        instrs = compile_to_instrs(self.SRC)
        back = bytecode.disassemble(bytecode.assemble(instrs))
        self.assertEqual([i.opcode for i in instrs], [i.opcode for i in back])
        self.assertEqual([{k: str(v) for k, v in i.operands.items()} for i in instrs],
                         [i.operands for i in back])

    def test_phase2_opcode_ids_unchanged(self):
        self.assertEqual(bytecode.OPCODE_ID["HALT"], 5)
        self.assertEqual(bytecode.OPCODE_ID["CHECK_RATE"], 2)

    def test_optimizer_still_collapses_repeat_checks(self):
        naive = compile_to_instrs(self.SRC, optimize=False)
        opt = compile_to_instrs(self.SRC, optimize=True)
        self.assertLess(len(opt), len(naive))


# ---------------------------------------------------------------- VM
class TestVMExecution(unittest.TestCase):
    def test_safe_demo_runs_without_alarms(self):
        result, _ = run_vm(read_demo("phase3_demo.smed"))
        self.assertEqual(result.status, "SAFE")
        self.assertEqual(result.alarms, [])

    def test_simulation_cumulative_doses_are_exact(self):
        result, _ = run_vm(read_demo("phase3_demo.smed"))
        self.assertAlmostEqual(result.cumulative[("p1", "dopamine")], 192.0)  # 8 mg/hr * 24
        self.assertAlmostEqual(result.cumulative[("p1", "heparin")], 120.0)   # 5 * 24
        self.assertAlmostEqual(result.cumulative[("p1", "morphine")], 24.0)   # 3 * 2 * 4
        self.assertAlmostEqual(result.cumulative[("p2", "dopamine")], 144.0)  # 6 * 24

    def test_horizon_defaults_to_longest_schedule(self):
        result, _ = run_vm(read_demo("phase3_demo.smed"))
        self.assertAlmostEqual(result.horizon_hr, 24.0)

    def test_horizon_override_changes_cumulative(self):
        result, _ = run_vm(read_demo("phase3_demo.smed"), horizon=12.0)
        self.assertAlmostEqual(result.cumulative[("p1", "dopamine")], 96.0)

    def test_runtime_monitor_catches_overlap_the_static_pass_cannot(self):
        # Compiles cleanly (each declaration is within its own limits) ...
        result, _ = run_vm(read_demo("phase3_alarm_demo.smed"))
        kinds = [a.kind for a in result.alarms]
        # ... but the bolus overlaps the continuous infusion: 12 + 12 = 24 > 20.
        self.assertEqual(kinds.count("RATE_EXCEEDED"), 4)
        self.assertEqual(kinds.count("TOTAL_EXCEEDED"), 1)
        self.assertEqual(result.status, "ALARM")

    def test_total_alarm_reports_exact_crossing_time(self):
        result, _ = run_vm(read_demo("phase3_alarm_demo.smed"))
        total = next(a for a in result.alarms if a.kind == "TOTAL_EXCEEDED")
        self.assertAlmostEqual(total.time_hr, 10.5)

    def test_rate_alarms_start_at_each_bolus(self):
        result, _ = run_vm(read_demo("phase3_alarm_demo.smed"))
        times = [a.time_hr for a in result.alarms if a.kind == "RATE_EXCEEDED"]
        self.assertEqual(times, [0.0, 6.0, 12.0, 18.0])

    def test_runtime_interaction_alarm(self):
        src = (HEAD + "INTERACTION dopamine WITH heparin LIMIT 18 mg/hr;\n"
               "INFUSION a FOR p1 USING heparin AT 5 mg/hr;\n"
               "REPEAT b FOR p1 USING dopamine AT 15 mg/hr EVERY 6 hr UNTIL 12 hr OVER 1 hr;")
        result, _ = run_vm(src)   # static: no continuous dopamine, so no static interaction
        self.assertIn("INTERACTION_EXCEEDED", [a.kind for a in result.alarms])

    def test_alarm_is_raised_once_per_violation_episode(self):
        result, _ = run_vm(read_demo("phase3_alarm_demo.smed"))
        rate_alarms = [a for a in result.alarms if a.kind == "RATE_EXCEEDED"]
        self.assertEqual(len(rate_alarms), 4)   # one per bolus, not one per event interval

    def test_instruction_count_is_reported(self):
        result, _ = run_vm(read_demo("phase3_demo.smed"))
        self.assertGreater(result.instructions_executed, 10)


class TestVMLoadVerification(unittest.TestCase):
    def _code(self):
        return bytecode.assemble(compile_to_instrs(read_demo("phase3_demo.smed")))

    def test_tampered_rate_is_rejected(self):
        bad = self._code().replace(b"8.000mg/hr", b"88.00mg/hr", 1)   # same length: 8 -> 88 mg/hr
        with self.assertRaises(VMError) as cm:
            MedsafeVM(bytecode.disassemble(bad)).run()
        self.assertIn("tampered", str(cm.exception))

    def test_tampered_verdict_is_rejected(self):
        bad = self._code().replace(b"SAFE", b"OKAY", 1)
        with self.assertRaises(VMError):
            MedsafeVM(bytecode.disassemble(bad)).run()

    def test_tampered_cumulative_total_is_rejected(self):
        bad = self._code().replace(b"24.000mg", b"90.000mg", 1)    # same length: 24 -> 90 mg > 60 mg cap
        with self.assertRaises(VMError):
            MedsafeVM(bytecode.disassemble(bad)).run()

    def test_missing_halt_is_rejected(self):
        instrs = [i for i in compile_to_instrs(read_demo("phase3_demo.smed")) if i.opcode != "HALT"]
        with self.assertRaises(VMError):
            MedsafeVM(instrs).load()

    def test_undefined_drug_reference_is_rejected(self):
        instrs = compile_to_instrs(read_demo("phase3_demo.smed"))
        instrs = [i for i in instrs if not (i.opcode == "DEF_DRUG" and i.operands["name"] == "morphine")]
        with self.assertRaises(VMError):
            MedsafeVM(instrs).load()

    def test_simulate_before_load_is_rejected(self):
        with self.assertRaises(VMError):
            MedsafeVM(compile_to_instrs(read_demo("phase3_demo.smed"))).simulate()

    def test_truncated_bytecode_raises_bytecode_error(self):
        code = self._code()
        for cut in (7, 40, len(code) // 2, len(code) - 1):
            with self.assertRaises(bytecode.BytecodeError):
                bytecode.disassemble(code[:cut])

    def test_length_changing_tamper_is_reported_as_corruption(self):
        bad = self._code().replace(b"8.000mg/hr", b"99.000mg/hr", 1)
        with self.assertRaises((bytecode.BytecodeError, VMError)):
            MedsafeVM(bytecode.disassemble(bad)).run()

    def test_bad_magic_number_is_rejected(self):
        with self.assertRaises(bytecode.BytecodeError):
            bytecode.disassemble(b"XXXX" + self._code()[4:])

    def test_load_log_lists_every_reverification(self):
        vm = MedsafeVM(bytecode.disassemble(self._code()))
        vm.load()
        self.assertTrue(any("re-verified OK" in line for line in vm.load_log))


# ---------------------------------------------------------------- CLI integration
def run_cli(*argv_files, **kw):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = medsafe_main.run(os.path.join(ROOT, argv_files[0]), False, False, False, False, False,
                                False, kw.pop("bytecode_out", None), **kw)
    return code, buf.getvalue()


class TestCLIIntegration(unittest.TestCase):
    def test_safe_demo_exits_zero(self):
        code, out = run_cli("phase3_demo.smed")
        self.assertEqual(code, 0)
        self.assertIn("COMPILATION SUCCESSFUL", out)
        self.assertIn("no alarms", out)

    def test_alarm_demo_exits_zero_by_default(self):
        code, out = run_cli("phase3_alarm_demo.smed")
        self.assertEqual(code, 0)
        self.assertIn("ALARM", out)

    def test_alarm_demo_exits_two_in_strict_mode(self):
        code, _ = run_cli("phase3_alarm_demo.smed", strict=True)
        self.assertEqual(code, 2)

    def test_static_errors_exit_one(self):
        for name in ("cumulative_error.smed", "interaction_error.smed", "over_error.smed"):
            code, out = run_cli(name)
            self.assertEqual(code, 1, name)
            self.assertIn("[Domain Semantic Error]", out)

    def test_perf_report_is_printed(self):
        code, out = run_cli("phase3_demo.smed", show_perf=True)
        self.assertEqual(code, 0)
        self.assertIn("[Performance]", out)
        self.assertIn("peak memory", out)

    def test_exec_precompiled_bytecode_matches_source_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "demo.medc")
            run_cli("phase3_demo.smed", bytecode_out=path)
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                code = medsafe_main.exec_bytecode(path, None, False, False)
            self.assertEqual(code, 0)
            self.assertIn("p1/dopamine: cumulative 192.000 mg", buf.getvalue())

    def test_exec_rejects_garbage_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "bad.medc")
            with open(path, "wb") as f:
                f.write(b"this is not bytecode")
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                code = medsafe_main.exec_bytecode(path, None, False, False)
            self.assertEqual(code, 1)

    def test_phase1_demo_still_compiles(self):
        code, _ = run_cli("valid.smed")
        self.assertEqual(code, 0)

    def test_phase1_syntax_error_still_reported(self):
        code, out = run_cli("syntax_error.smed")
        self.assertEqual(code, 1)
        self.assertIn("[Syntax Error]", out)


if __name__ == "__main__":
    unittest.main()
