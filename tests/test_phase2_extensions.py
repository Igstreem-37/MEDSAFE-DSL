import sys, os, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from lexer import Lexer
from parser import Parser, SyntaxErrorMEDSAFE
from semantic import SemanticAnalyzer, SemanticError, ReferenceError_

MULTI_DRUG_SRC = """
PATIENT p1 { WEIGHT: 70 kg; }
DRUG dopamine { MAX_RATE: 20 mg/hr; }
DRUG heparin { MAX_RATE: 15 mg/hr; }
INFUSION combo FOR p1 USING dopamine AT 10 mg/hr, heparin AT 5 mg/hr;
"""

MULTI_DRUG_UNSAFE_SRC = """
PATIENT p1 { WEIGHT: 70 kg; }
DRUG dopamine { MAX_RATE: 20 mg/hr; }
DRUG heparin { MAX_RATE: 15 mg/hr; }
INFUSION combo FOR p1 USING dopamine AT 10 mg/hr, heparin AT 25 mg/hr;
"""

CONDITIONAL_HEAVY_SRC = """
PATIENT p1 { WEIGHT: 70 kg; }
DRUG dopamine { MAX_RATE: 20 mg/hr; }
INFUSION tiered FOR p1 USING dopamine IF WEIGHT >= 50 kg THEN 18 mg/hr ELSE 8 mg/hr;
"""

CONDITIONAL_LIGHT_SRC = """
PATIENT p2 { WEIGHT: 30 kg; }
DRUG dopamine { MAX_RATE: 20 mg/hr; }
INFUSION tiered FOR p2 USING dopamine IF WEIGHT >= 50 kg THEN 18 mg/hr ELSE 8 mg/hr;
"""

CONDITIONAL_UNSAFE_BRANCH_SRC = """
PATIENT p1 { WEIGHT: 70 kg; }
DRUG dopamine { MAX_RATE: 20 mg/hr; }
INFUSION tiered FOR p1 USING dopamine IF WEIGHT >= 50 kg THEN 25 mg/hr ELSE 8 mg/hr;
"""

REPEAT_SRC = """
PATIENT p1 { WEIGHT: 70 kg; }
DRUG dopamine { MAX_RATE: 20 mg/hr; }
REPEAT r1 FOR p1 USING dopamine AT 10 mg/hr EVERY 4 hr UNTIL 24 hr;
"""

REPEAT_UNSAFE_RATE_SRC = """
PATIENT p1 { WEIGHT: 70 kg; }
DRUG dopamine { MAX_RATE: 20 mg/hr; }
REPEAT r1 FOR p1 USING dopamine AT 25 mg/hr EVERY 4 hr UNTIL 24 hr;
"""

REPEAT_BAD_BOUNDS_SRC = """
PATIENT p1 { WEIGHT: 70 kg; }
DRUG dopamine { MAX_RATE: 20 mg/hr; }
REPEAT r1 FOR p1 USING dopamine AT 10 mg/hr EVERY 24 hr UNTIL 4 hr;
"""


class TestMultiDrugInfusion(unittest.TestCase):
    def _analyze(self, src):
        program = Parser(Lexer(src).tokenize()).parse_program()
        analyzer = SemanticAnalyzer(program)
        analyzer.analyze()
        return analyzer

    def test_parses_multiple_drug_bindings(self):
        program = Parser(Lexer(MULTI_DRUG_SRC).tokenize()).parse_program()
        inf = program.infusions[0]
        self.assertEqual([b.drug for b in inf.bindings], ["dopamine", "heparin"])

    def test_checks_every_binding_and_produces_two_checks(self):
        analyzer = self._analyze(MULTI_DRUG_SRC)
        subjects = [c.subject for c in analyzer.checks]
        self.assertIn("combo[dopamine]", subjects)
        self.assertIn("combo[heparin]", subjects)

    def test_unsafe_binding_in_multidrug_infusion_raises(self):
        program = Parser(Lexer(MULTI_DRUG_UNSAFE_SRC).tokenize()).parse_program()
        with self.assertRaises(SemanticError):
            SemanticAnalyzer(program).analyze()


class TestConditionalInfusion(unittest.TestCase):
    def _analyze(self, src):
        program = Parser(Lexer(src).tokenize()).parse_program()
        analyzer = SemanticAnalyzer(program)
        analyzer.analyze()
        return analyzer

    def test_parses_conditional_binding(self):
        program = Parser(Lexer(CONDITIONAL_HEAVY_SRC).tokenize()).parse_program()
        inf = program.infusions[0]
        self.assertIsNotNone(inf.conditional)
        self.assertEqual(inf.conditional.comparator, ">=")

    def test_heavy_patient_resolves_then_branch(self):
        analyzer = self._analyze(CONDITIONAL_HEAVY_SRC)
        check = analyzer.checks[0]
        self.assertEqual(check.detail["branch"], "THEN")
        self.assertAlmostEqual(check.rate_mg_per_hr, 18.0)

    def test_light_patient_resolves_else_branch(self):
        analyzer = self._analyze(CONDITIONAL_LIGHT_SRC)
        check = analyzer.checks[0]
        self.assertEqual(check.detail["branch"], "ELSE")
        self.assertAlmostEqual(check.rate_mg_per_hr, 8.0)

    def test_unsafe_resolved_branch_raises(self):
        program = Parser(Lexer(CONDITIONAL_UNSAFE_BRANCH_SRC).tokenize()).parse_program()
        with self.assertRaises(SemanticError):
            SemanticAnalyzer(program).analyze()


class TestRepeatInfusion(unittest.TestCase):
    def _analyze(self, src):
        program = Parser(Lexer(src).tokenize()).parse_program()
        analyzer = SemanticAnalyzer(program)
        analyzer.analyze()
        return analyzer

    def test_parses_repeat_decl(self):
        program = Parser(Lexer(REPEAT_SRC).tokenize()).parse_program()
        self.assertEqual(len(program.repeats), 1)
        rep = program.repeats[0]
        self.assertEqual((rep.patient, rep.drug), ("p1", "dopamine"))

    def test_computes_correct_repeat_count(self):
        analyzer = self._analyze(REPEAT_SRC)
        check = analyzer.checks[0]
        self.assertEqual(check.detail["repeat_count"], 6)  # 24hr / 4hr

    def test_unsafe_repeat_rate_raises(self):
        program = Parser(Lexer(REPEAT_UNSAFE_RATE_SRC).tokenize()).parse_program()
        with self.assertRaises(SemanticError):
            SemanticAnalyzer(program).analyze()

    def test_until_shorter_than_interval_raises(self):
        program = Parser(Lexer(REPEAT_BAD_BOUNDS_SRC).tokenize()).parse_program()
        with self.assertRaises(SemanticError):
            SemanticAnalyzer(program).analyze()


if __name__ == "__main__":
    unittest.main()
