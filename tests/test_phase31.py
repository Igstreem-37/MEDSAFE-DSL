"""Phase 3.1 tests: static same-drug concurrency analysis."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

from semantic import SemanticError
from test_phase3 import analyze, run_vm, read_demo, compile_to_instrs

HEAD = """
PATIENT p1 { WEIGHT: 70 kg; }
PATIENT p2 { WEIGHT: 30 kg; }
DRUG dopamine { MAX_RATE: 20 mg/hr; }
DRUG heparin { MAX_RATE: 15 mg/hr; }
"""


class TestConcurrentSameDrug(unittest.TestCase):
    def test_two_infusions_are_summed(self):
        src = HEAD + "INFUSION a FOR p1 USING dopamine AT 12 mg/hr;\nINFUSION b FOR p1 USING dopamine AT 10 mg/hr;"
        with self.assertRaises(SemanticError) as cm:
            analyze(src)
        self.assertIn("22.000 mg/hr", str(cm.exception))
        self.assertIn("concurrent infusions of 'dopamine'", str(cm.exception))

    def test_error_is_reported_at_later_declaration(self):
        src = HEAD + "INFUSION a FOR p1 USING dopamine AT 12 mg/hr;\nINFUSION b FOR p1 USING dopamine AT 10 mg/hr;"
        with self.assertRaises(SemanticError) as cm:
            analyze(src)
        self.assertEqual(cm.exception.line, 7)

    def test_exactly_at_limit_is_allowed(self):
        src = HEAD + "INFUSION a FOR p1 USING dopamine AT 12 mg/hr;\nINFUSION b FOR p1 USING dopamine AT 8 mg/hr;"
        _, _, a = analyze(src)
        self.assertAlmostEqual(a.concurrency_checks[0].peak_mg_per_hr, 20.0)

    def test_different_patients_are_not_summed(self):
        src = HEAD + "INFUSION a FOR p1 USING dopamine AT 15 mg/hr;\nINFUSION b FOR p2 USING dopamine AT 15 mg/hr;"
        _, _, a = analyze(src)
        self.assertEqual(a.concurrency_checks, [])

    def test_different_drugs_are_not_summed(self):
        src = HEAD + "INFUSION a FOR p1 USING dopamine AT 15 mg/hr;\nINFUSION b FOR p1 USING heparin AT 14 mg/hr;"
        _, _, a = analyze(src)
        self.assertEqual(a.concurrency_checks, [])

    def test_single_source_has_no_concurrency_check(self):
        _, _, a = analyze(HEAD + "INFUSION a FOR p1 USING dopamine AT 15 mg/hr;")
        self.assertEqual(a.concurrency_checks, [])

    def test_infusion_plus_repeat_overlap_is_rejected(self):
        src = HEAD + ("INFUSION a FOR p1 USING dopamine AT 12 mg/hr;\n"
                      "REPEAT r FOR p1 USING dopamine AT 12 mg/hr EVERY 6 hr UNTIL 24 hr OVER 1 hr;")
        with self.assertRaises(SemanticError) as cm:
            analyze(src)
        self.assertIn("24.000 mg/hr at t=0hr", str(cm.exception))

    def test_two_repeats_overlap_at_t0(self):
        src = HEAD + ("REPEAT r1 FOR p1 USING dopamine AT 12 mg/hr EVERY 6 hr UNTIL 24 hr OVER 1 hr;\n"
                      "REPEAT r2 FOR p1 USING dopamine AT 12 mg/hr EVERY 8 hr UNTIL 24 hr OVER 1 hr;")
        with self.assertRaises(SemanticError):
            analyze(src)

    def test_conditional_infusion_uses_resolved_branch(self):
        src = HEAD + ("INFUSION c FOR p1 USING dopamine IF WEIGHT >= 50 kg THEN 18 mg/hr ELSE 4 mg/hr;\n"
                      "INFUSION d FOR p1 USING dopamine AT 5 mg/hr;")
        with self.assertRaises(SemanticError):        # 70 kg -> THEN branch: 18 + 5 = 23
            analyze(src)
        light = src.replace("FOR p1 USING dopamine IF", "FOR p2 USING dopamine IF")
        analyze(light)                                # 30 kg -> ELSE branch, other patient

    def test_units_are_normalized_before_summing(self):
        src = HEAD + ("INFUSION a FOR p1 USING dopamine AT 10 mg/hr;\n"
                      "INFUSION b FOR p1 USING dopamine AT 200 mcg/min;")   # 12 mg/hr
        with self.assertRaises(SemanticError):
            analyze(src)

    def test_multidrug_infusion_binding_is_summed_with_others(self):
        src = HEAD + ("INFUSION m FOR p1 USING dopamine AT 12 mg/hr, heparin AT 5 mg/hr;\n"
                      "INFUSION n FOR p1 USING dopamine AT 12 mg/hr;")
        with self.assertRaises(SemanticError):
            analyze(src)

    def test_peak_time_and_sources_recorded(self):
        src = HEAD + ("INFUSION a FOR p1 USING dopamine AT 5 mg/hr;\n"
                      "REPEAT r FOR p1 USING dopamine AT 10 mg/hr EVERY 6 hr UNTIL 12 hr OVER 1 hr;")
        _, _, a = analyze(src)
        cc = a.concurrency_checks[0]
        self.assertAlmostEqual(cc.peak_mg_per_hr, 15.0)
        self.assertEqual(sorted(cc.sources), ["a", "r"])

    def test_phase2_demo_is_now_a_compile_time_error(self):
        with self.assertRaises(SemanticError) as cm:
            analyze(read_demo("phase2_demo.smed"))
        self.assertIn("38.000 mg/hr", str(cm.exception))

    def test_phase3_demos_still_compile(self):
        for name in ("phase3_demo.smed", "phase3_alarm_demo.smed", "valid.smed"):
            analyze(read_demo(name))

    def test_concurrent_error_demo_is_rejected(self):
        with self.assertRaises(SemanticError):
            analyze(read_demo("concurrent_error.smed"))


class TestStaticMatchesRuntime(unittest.TestCase):
    """The static peak must equal the VM's simulated peak: the compile-time
    proof and the runtime monitor compute the same quantity."""
    PROGRAMS = [
        HEAD + "INFUSION a FOR p1 USING dopamine AT 5 mg/hr;\nINFUSION b FOR p1 USING dopamine AT 7 mg/hr;",
        HEAD + ("INFUSION a FOR p1 USING dopamine AT 5 mg/hr;\n"
                "REPEAT r FOR p1 USING dopamine AT 10 mg/hr EVERY 6 hr UNTIL 24 hr OVER 2 hr;"),
        HEAD + ("REPEAT r1 FOR p1 USING dopamine AT 6 mg/hr EVERY 4 hr UNTIL 24 hr OVER 1 hr;\n"
                "REPEAT r2 FOR p1 USING dopamine AT 7 mg/hr EVERY 6 hr UNTIL 24 hr OVER 3 hr;"),
    ]

    def test_static_peak_equals_vm_peak(self):
        for src in self.PROGRAMS:
            _, _, a = analyze(src)
            result, _ = run_vm(src)
            static_peak = a.concurrency_checks[0].peak_mg_per_hr
            self.assertAlmostEqual(static_peak, result.peak_rate[("p1", "dopamine")], msg=src)
            self.assertEqual(result.alarms, [])

    def test_concurrency_check_listed_in_diagnostics_only_when_multiple_sources(self):
        _, _, a = analyze(self.PROGRAMS[0])
        self.assertEqual(len(a.concurrency_checks), 1)


if __name__ == "__main__":
    unittest.main()
