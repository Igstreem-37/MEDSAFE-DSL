import sys, os, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from lexer import Lexer
from parser import Parser
from semantic import SemanticAnalyzer, SemanticError, ReferenceError_, normalize_to_mg_per_hr
from ast_nodes import Quantity

SAFE_SRC = """
PATIENT p1 { WEIGHT: 70 kg; }
DRUG dopamine { MAX_RATE: 20 mg/hr; }
INFUSION inf1 FOR p1 USING dopamine AT 15 mg/hr;
"""

UNSAFE_SRC = """
PATIENT p2 { WEIGHT: 65 kg; }
DRUG heparin { MAX_RATE: 10 mg/hr; }
INFUSION inf2 FOR p2 USING heparin AT 25 mg/hr;
"""

UNDECLARED_PATIENT_SRC = """
DRUG heparin { MAX_RATE: 10 mg/hr; }
INFUSION inf2 FOR ghost USING heparin AT 5 mg/hr;
"""


class TestSemanticAnalyzer(unittest.TestCase):

    def _analyze(self, src):
        program = Parser(Lexer(src).tokenize()).parse_program()
        return SemanticAnalyzer(program).analyze()

    def test_unit_normalization_mg_hr_identity(self):
        self.assertAlmostEqual(normalize_to_mg_per_hr(Quantity(20, "mg", "hr")), 20.0)

    def test_unit_normalization_mcg_to_mg(self):
        self.assertAlmostEqual(normalize_to_mg_per_hr(Quantity(1000, "mcg", "hr")), 1.0)

    def test_unit_normalization_per_minute_to_per_hour(self):
        self.assertAlmostEqual(normalize_to_mg_per_hr(Quantity(1, "mg", "min")), 60.0)

    def test_safe_infusion_passes(self):
        program = Parser(Lexer(SAFE_SRC).tokenize()).parse_program()
        analyzer = SemanticAnalyzer(program)
        analyzer.analyze()
        self.assertEqual(analyzer.diagnostics[0].verdict, "SAFE")

    def test_unsafe_infusion_raises_semantic_error(self):
        with self.assertRaises(SemanticError):
            self._analyze(UNSAFE_SRC)

    def test_undeclared_patient_reference_raises(self):
        with self.assertRaises(ReferenceError_):
            self._analyze(UNDECLARED_PATIENT_SRC)

    def test_symbol_table_populated_after_analysis(self):
        symtab = self._analyze(SAFE_SRC)
        self.assertIsNotNone(symtab.lookup("p1"))
        self.assertIsNotNone(symtab.lookup("dopamine"))


if __name__ == "__main__":
    unittest.main()
