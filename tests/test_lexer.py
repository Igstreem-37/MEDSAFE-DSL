import sys, os, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from lexer import Lexer, LexicalError
from tokens import TokenType


class TestLexer(unittest.TestCase):

    def test_keyword_recognition(self):
        toks = Lexer("PATIENT").tokenize()
        self.assertEqual(toks[0].type, TokenType.PATIENT)

    def test_identifier_recognition(self):
        toks = Lexer("p1").tokenize()
        self.assertEqual(toks[0].type, TokenType.IDENT)

    def test_number_literal(self):
        toks = Lexer("70").tokenize()
        self.assertEqual(toks[0].type, TokenType.NUMBER)
        self.assertEqual(toks[0].lexeme, "70")

    def test_decimal_number_literal(self):
        toks = Lexer("2.5").tokenize()
        self.assertEqual(toks[0].lexeme, "2.5")

    def test_unit_recognition(self):
        toks = Lexer("mg").tokenize()
        self.assertEqual(toks[0].type, TokenType.UNIT)

    def test_symbols(self):
        toks = Lexer("{ } : ; /").tokenize()
        kinds = [t.type for t in toks[:5]]
        self.assertEqual(kinds, [TokenType.LBRACE, TokenType.RBRACE,
                                  TokenType.COLON, TokenType.SEMI, TokenType.SLASH])

    def test_comment_is_skipped(self):
        toks = Lexer("# a comment\nPATIENT").tokenize()
        self.assertEqual(toks[0].type, TokenType.PATIENT)
        self.assertEqual(toks[0].line, 2)

    def test_line_column_tracking(self):
        toks = Lexer("PATIENT p1\nDRUG d1").tokenize()
        drug_tok = next(t for t in toks if t.type == TokenType.DRUG)
        self.assertEqual((drug_tok.line, drug_tok.col), (2, 1))

    def test_eof_token_present(self):
        toks = Lexer("PATIENT").tokenize()
        self.assertEqual(toks[-1].type, TokenType.EOF)

    def test_illegal_character_raises(self):
        with self.assertRaises(LexicalError):
            Lexer("PATIENT p1 @").tokenize()


if __name__ == "__main__":
    unittest.main()
