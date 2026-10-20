"""
lexer.py
Deterministic, hand-crafted lexical analyzer for MEDSAFE-DSL.
No parser-generator tooling is used; tokenization is performed with a single
compiled master regular expression (re module) evaluated left-to-right over
the source buffer, in the classical "maximal munch" style.
"""
import re
from tokens import Token, TokenType

KEYWORDS = {
    "PATIENT": TokenType.PATIENT,
    "DRUG": TokenType.DRUG,
    "INFUSION": TokenType.INFUSION,
    "WEIGHT": TokenType.WEIGHT,
    "MAX_RATE": TokenType.MAX_RATE,
    "FOR": TokenType.FOR,
    "USING": TokenType.USING,
    "AT": TokenType.AT,
    "IF": TokenType.IF,
    "THEN": TokenType.THEN,
    "ELSE": TokenType.ELSE,
    "REPEAT": TokenType.REPEAT,
    "EVERY": TokenType.EVERY,
    "UNTIL": TokenType.UNTIL,
    "MAX_TOTAL": TokenType.MAX_TOTAL,
    "OVER": TokenType.OVER,
    "INTERACTION": TokenType.INTERACTION,
    "WITH": TokenType.WITH,
    "LIMIT": TokenType.LIMIT,
}

UNITS = {"ml", "mg", "hr", "kg", "min", "mcg", "L"}

TOKEN_SPEC = [
    ("SKIP",     r"[ \t]+"),
    ("COMMENT",  r"#[^\n]*"),
    ("NEWLINE",  r"\n"),
    ("NUMBER",   r"\d+(\.\d+)?"),
    ("IDENT",    r"[A-Za-z_][A-Za-z0-9_]*"),
    ("LBRACE",   r"\{"),
    ("RBRACE",   r"\}"),
    ("COLON",    r":"),
    ("SEMI",     r";"),
    ("SLASH",    r"/"),
    ("COMMA",    r","),
    # Two-character comparators MUST be tried before their single-char prefixes
    # (maximal munch): >= before >, <= before <.
    ("GTE",      r">="),
    ("LTE",      r"<="),
    ("EQEQ",     r"=="),
    ("GT",       r">"),
    ("LT",       r"<"),
    ("MISMATCH", r"."),
]

MASTER_RE = re.compile("|".join(f"(?P<{name}>{pattern})" for name, pattern in TOKEN_SPEC))


class LexicalError(Exception):
    def __init__(self, message: str, line: int, col: int):
        super().__init__(f"[Lexical Error] {message} at line {line}, column {col}")
        self.line = line
        self.col = col


class Lexer:
    """Converts raw MEDSAFE-DSL source text into a flat list of Token objects."""

    def __init__(self, source: str):
        self.source = source

    def tokenize(self) -> list[Token]:
        tokens: list[Token] = []
        line = 1
        line_start = 0

        for match in MASTER_RE.finditer(self.source):
            kind = match.lastgroup
            lexeme = match.group()
            col = match.start() - line_start + 1

            if kind == "NEWLINE":
                line += 1
                line_start = match.end()
                continue
            if kind in ("SKIP", "COMMENT"):
                continue
            if kind == "MISMATCH":
                raise LexicalError(f"unexpected character {lexeme!r}", line, col)

            if kind == "IDENT":
                if lexeme in KEYWORDS:
                    tokens.append(Token(KEYWORDS[lexeme], lexeme, line, col))
                elif lexeme in UNITS:
                    tokens.append(Token(TokenType.UNIT, lexeme, line, col))
                else:
                    tokens.append(Token(TokenType.IDENT, lexeme, line, col))
            elif kind == "NUMBER":
                tokens.append(Token(TokenType.NUMBER, lexeme, line, col))
            else:
                tokens.append(Token(TokenType[kind], lexeme, line, col))

        tokens.append(Token(TokenType.EOF, "", line, self._col(len(self.source), line_start)))
        return tokens

    @staticmethod
    def _col(pos: int, line_start: int) -> int:
        return pos - line_start + 1
