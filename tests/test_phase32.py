"""Phase 3.2 tests: INFUSION ... OVER (bounded infusions), static MAX_TOTAL for
bounded infusions, and pulse-based interaction checking including REPEAT doses."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

import bytecode
from parser import SyntaxErrorMEDSAFE
from semantic import SemanticError
from test_phase3 import analyze, parse, run_vm, read_demo, compile_to_instrs

HEAD = """
PATIENT p1 { WEIGHT: 70 kg; }
PATIENT p2 { WEIGHT: 30 kg; }
DRUG dopamine { MAX_RATE: 20 mg/hr; MAX_TOTAL: 100 mg; }
DRUG heparin { MAX_RATE: 15 mg/hr; }
DRUG morphine { MAX_RATE: 10 mg/hr; }
"""


class TestInfusionOverGrammar(unittest.TestCase):
    def test_plain_infusion_with_over_parses(self):
        i = parse(HEAD + "INFUSION a FOR p1 USING dopamine AT 5 mg/hr OVER 6 hr;").infusions[0]
        self.assertEqual((i.duration.value, i.duration.unit), (6.0, "hr"))

    def test_multidrug_infusion_with_over_parses(self):
        i = parse(HEAD + "INFUSION a FOR p1 USING dopamine AT 5 mg/hr, heparin AT 2 mg/hr OVER 90 min;").infusions[0]
        self.assertEqual(i.duration.unit, "min")
        self.assertEqual(len(i.bindings), 2)

    def test_conditional_infusion_with_over_parses(self):
        i = parse(HEAD + "INFUSION a FOR p1 USING dopamine IF WEIGHT >= 50 kg THEN 9 mg/hr ELSE 3 mg/hr OVER 4 hr;").infusions[0]
        self.assertIsNotNone(i.conditional)
        self.assertEqual(i.duration.value, 4.0)

    def test_infusion_without_over_still_parses(self):
        self.assertIsNone(parse(HEAD + "INFUSION a FOR p1 USING dopamine AT 5 mg/hr;").infusions[0].duration)

    def test_over_missing_unit_is_syntax_error(self):
        with self.assertRaises(SyntaxErrorMEDSAFE):
            parse(HEAD + "INFUSION a FOR p1 USING dopamine AT 5 mg/hr OVER 6;")

    def test_non_positive_over_is_semantic_error(self):
        with self.assertRaises(SemanticError):
            analyze(HEAD + "INFUSION a FOR p1 USING dopamine AT 5 mg/hr OVER 0 hr;")


class TestBoundedInfusionCumulative(unittest.TestCase):
    def test_bounded_infusion_total_is_rate_times_duration(self):
        _, _, a = analyze(HEAD + "INFUSION a FOR p1 USING dopamine AT 5 mg/hr OVER 10 hr;")
        t = a.total_checks[0]
        self.assertAlmostEqual(t.total_mg, 50.0)
        self.assertEqual(t.contributors, ["a"])

    def test_bounded_infusion_over_max_total_is_rejected(self):
        with self.assertRaises(SemanticError) as cm:
            analyze(HEAD + "INFUSION a FOR p1 USING dopamine AT 12 mg/hr OVER 10 hr;")   # 120 > 100
        self.assertIn("after infusion 'a'", str(cm.exception))
        self.assertIn("120.000 mg", str(cm.exception))

    def test_exactly_at_max_total_is_allowed(self):
        analyze(HEAD + "INFUSION a FOR p1 USING dopamine AT 10 mg/hr OVER 10 hr;")       # 100 = 100

    def test_bounded_infusion_and_repeat_totals_add(self):
        src = HEAD + ("INFUSION a FOR p1 USING dopamine AT 5 mg/hr OVER 10 hr;\n"       # 50
                      "REPEAT r FOR p1 USING dopamine AT 5 mg/hr EVERY 6 hr UNTIL 24 hr OVER 3 hr;")  # 60
        with self.assertRaises(SemanticError) as cm:
            analyze(src)
        self.assertIn("110.000 mg", str(cm.exception))

    def test_minutes_are_normalized(self):
        _, _, a = analyze(HEAD + "INFUSION a FOR p1 USING dopamine AT 6 mg/hr OVER 90 min;")
        self.assertAlmostEqual(a.total_checks[0].total_mg, 9.0)

    def test_unbounded_infusion_is_not_totalled_statically(self):
        _, _, a = analyze(HEAD + "INFUSION a FOR p1 USING dopamine AT 12 mg/hr;")
        self.assertEqual(a.total_checks, [])

    def test_totals_are_per_patient(self):
        src = HEAD + ("INFUSION a FOR p1 USING dopamine AT 10 mg/hr OVER 10 hr;\n"
                      "INFUSION b FOR p2 USING dopamine AT 10 mg/hr OVER 10 hr;")
        analyze(src)       # 100 each, not 200 together

    def test_phase3_repeat_cumulative_error_message_unchanged(self):
        with self.assertRaises(SemanticError) as cm:
            analyze(read_demo("cumulative_error.smed"))
        self.assertIn("after repeat 'r1'", str(cm.exception))


class TestBoundedInfusionConcurrency(unittest.TestCase):
    def test_non_overlapping_windows_are_not_summed_after_end(self):
        # a runs [0,2), b runs [0,6): overlap only in [0,2) -> peak 12 + 8 = 20 (allowed)
        src = HEAD + ("INFUSION a FOR p1 USING dopamine AT 12 mg/hr OVER 2 hr;\n"
                      "INFUSION b FOR p1 USING dopamine AT 8 mg/hr OVER 6 hr;")
        _, _, a = analyze(src)
        self.assertAlmostEqual(a.concurrency_checks[0].peak_mg_per_hr, 20.0)

    def test_bounded_infusions_still_overlap_at_t0(self):
        src = HEAD + ("INFUSION a FOR p1 USING dopamine AT 12 mg/hr OVER 2 hr;\n"
                      "INFUSION b FOR p1 USING dopamine AT 12 mg/hr OVER 6 hr;")
        with self.assertRaises(SemanticError):
            analyze(src)

    def test_repeat_first_dose_overlaps_bounded_infusion(self):
        # Every REPEAT starts at t=0, so its first dose overlaps the bounded infusion: 15 + 10 = 25 > 20.
        src = HEAD + ("INFUSION a FOR p1 USING dopamine AT 15 mg/hr OVER 1 hr;\n"
                      "REPEAT r FOR p1 USING dopamine AT 10 mg/hr EVERY 6 hr UNTIL 12 hr OVER 1 hr;")
        with self.assertRaises(SemanticError):
            analyze(src)


class TestPulseInteractions(unittest.TestCase):
    def test_interaction_with_repeat_dose_is_rejected_statically(self):
        src = HEAD + ("INTERACTION dopamine WITH heparin LIMIT 18 mg/hr;\n"
                      "INFUSION a FOR p1 USING heparin AT 5 mg/hr;\n"
                      "REPEAT b FOR p1 USING dopamine AT 15 mg/hr EVERY 6 hr UNTIL 12 hr OVER 1 hr;")
        with self.assertRaises(SemanticError) as cm:
            analyze(src)
        self.assertIn("20.000 mg/hr", str(cm.exception))
        self.assertIn("at t=0hr", str(cm.exception))

    def test_interaction_at_exact_limit_is_allowed(self):
        src = HEAD + ("INTERACTION dopamine WITH heparin LIMIT 20 mg/hr;\n"
                      "INFUSION a FOR p1 USING heparin AT 5 mg/hr;\n"
                      "REPEAT b FOR p1 USING dopamine AT 15 mg/hr EVERY 6 hr UNTIL 12 hr OVER 1 hr;")
        _, _, a = analyze(src)
        self.assertAlmostEqual(a.interaction_checks[0].combined_mg_per_hr, 20.0)

    def test_drugs_not_given_together_do_not_interact(self):
        # Drugs given to DIFFERENT patients never interact.
        src = HEAD + ("INTERACTION dopamine WITH heparin LIMIT 5 mg/hr;\n"
                      "INFUSION a FOR p1 USING dopamine AT 15 mg/hr;\n"
                      "INFUSION b FOR p2 USING heparin AT 14 mg/hr;")
        _, _, a = analyze(src)
        self.assertEqual(a.interaction_checks, [])

    def test_interaction_uses_bounded_infusion_window(self):
        src = HEAD + ("INTERACTION dopamine WITH heparin LIMIT 12 mg/hr;\n"
                      "INFUSION a FOR p1 USING dopamine AT 10 mg/hr OVER 2 hr;\n"
                      "INFUSION b FOR p1 USING heparin AT 5 mg/hr;")
        with self.assertRaises(SemanticError):
            analyze(src)

    def test_interaction_peak_time_recorded(self):
        src = HEAD + ("INTERACTION dopamine WITH heparin LIMIT 30 mg/hr;\n"
                      "INFUSION a FOR p1 USING heparin AT 5 mg/hr;\n"
                      "REPEAT b FOR p1 USING dopamine AT 15 mg/hr EVERY 6 hr UNTIL 12 hr OVER 1 hr;")
        _, _, a = analyze(src)
        self.assertEqual(a.interaction_checks[0].peak_time_hr, 0.0)

    def test_phase3_continuous_interaction_error_still_raised(self):
        with self.assertRaises(SemanticError) as cm:
            analyze(read_demo("interaction_error.smed"))
        self.assertIn("combined rate of 15.000 mg/hr", str(cm.exception))

    def test_vm_still_catches_interaction_if_static_pass_is_absent(self):
        src = HEAD + ("INTERACTION dopamine WITH heparin LIMIT 18 mg/hr;\n"
                      "INFUSION a FOR p1 USING heparin AT 5 mg/hr;\n"
                      "REPEAT b FOR p1 USING dopamine AT 15 mg/hr EVERY 6 hr UNTIL 12 hr OVER 1 hr;")
        result, _ = run_vm(src, skip_interactions=True)
        self.assertIn("INTERACTION_EXCEEDED", [al.kind for al in result.alarms])


class TestVMBoundedInfusion(unittest.TestCase):
    def test_ir_carries_duration_only_when_bounded(self):
        ir = compile_to_instrs(HEAD + "INFUSION a FOR p1 USING dopamine AT 5 mg/hr OVER 4 hr;\n"
                                       "INFUSION b FOR p1 USING heparin AT 2 mg/hr;")
        infuse = {i.operands["subject"]: i.operands for i in ir if i.opcode == "INFUSE"}
        self.assertIn("duration_hr", infuse["a"])
        self.assertNotIn("duration_hr", infuse["b"])

    def test_vm_simulates_bounded_infusion_exactly(self):
        result, _ = run_vm(HEAD + "INFUSION a FOR p1 USING dopamine AT 5 mg/hr OVER 4 hr;")
        self.assertAlmostEqual(result.cumulative[("p1", "dopamine")], 20.0)
        self.assertAlmostEqual(result.horizon_hr, 4.0)

    def test_vm_cumulative_equals_static_total(self):
        src = HEAD + ("INFUSION a FOR p1 USING dopamine AT 5 mg/hr OVER 10 hr;\n"
                      "REPEAT r FOR p1 USING dopamine AT 4 mg/hr EVERY 6 hr UNTIL 24 hr OVER 2 hr;")
        _, _, a = analyze(src)
        result, _ = run_vm(src)
        self.assertAlmostEqual(a.total_checks[0].total_mg, result.cumulative[("p1", "dopamine")])
        self.assertEqual(result.alarms, [])

    def test_bounded_and_unbounded_mix(self):
        result, _ = run_vm(HEAD + "INFUSION a FOR p1 USING dopamine AT 5 mg/hr OVER 4 hr;\n"
                                   "INFUSION b FOR p1 USING heparin AT 2 mg/hr;", horizon=10.0)
        self.assertAlmostEqual(result.cumulative[("p1", "dopamine")], 20.0)
        self.assertAlmostEqual(result.cumulative[("p1", "heparin")], 20.0)

    def test_static_interaction_peak_matches_vm_behaviour(self):
        src = HEAD + ("INTERACTION dopamine WITH heparin LIMIT 20 mg/hr;\n"
                      "INFUSION a FOR p1 USING heparin AT 5 mg/hr;\n"
                      "REPEAT b FOR p1 USING dopamine AT 15 mg/hr EVERY 6 hr UNTIL 12 hr OVER 1 hr;")
        _, _, a = analyze(src)
        result, _ = run_vm(src)
        self.assertEqual(result.alarms, [])          # static says exactly 20 = limit; VM agrees

    def test_old_bytecode_without_duration_still_loads(self):
        code = bytecode.assemble(compile_to_instrs(read_demo("phase3_demo.smed")))
        self.assertEqual(run_vm(read_demo("phase3_demo.smed"))[0].status, "SAFE")
        self.assertTrue(code.startswith(b"MDSC"))


if __name__ == "__main__":
    unittest.main()
