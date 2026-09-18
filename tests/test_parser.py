import sys, os, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from lexer import Lexer
from parser import Parser, SyntaxErrorMEDSAFE

VALID_SRC = """
PATIENT p1 { WEIGHT: 70 kg; }
DRUG dopamine { MAX_RATE: 20 mg/hr; }
INFUSION inf1 FOR p1 USING dopamine AT 15 mg/hr;
"""


class TestParser(unittest.TestCase):

    def _parse(self, src):
        return Parser(Lexer(src).tokenize()).parse_program()

    def test_parses_patient_decl(self):
        program = self._parse(VALID_SRC)
        self.assertEqual(len(program.patients), 1)
        self.assertEqual(program.patients[0].name, "p1")

    def test_parses_drug_decl(self):
        program = self._parse(VALID_SRC)
        self.assertEqual(program.drugs[0].max_rate.value, 20.0)

    def test_parses_infusion_decl(self):
        program = self._parse(VALID_SRC)
        inf = program.infusions[0]
        self.assertEqual((inf.patient, inf.drug), ("p1", "dopamine"))

    def test_missing_semicolon_raises_syntax_error(self):
        bad = "PATIENT p3 { WEIGHT: 80 kg }"
        with self.assertRaises(SyntaxErrorMEDSAFE):
            self._parse(bad)

    def test_missing_brace_raises_syntax_error(self):
        bad = "PATIENT p3 WEIGHT: 80 kg; }"
        with self.assertRaises(SyntaxErrorMEDSAFE):
            self._parse(bad)

    def test_unknown_top_level_token_raises(self):
        with self.assertRaises(SyntaxErrorMEDSAFE):
            self._parse("BANANA x;")

    def test_multiple_declarations_parsed_in_order(self):
        program = self._parse(VALID_SRC)
        self.assertEqual(len(program.patients) + len(program.drugs) + len(program.infusions), 3)


if __name__ == "__main__":
    unittest.main()
