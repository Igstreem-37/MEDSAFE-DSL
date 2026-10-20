"""
tokens.py
Token type definitions and the Token record for MEDSAFE-DSL.
Built exclusively on the Python 3.10+ standard library (enum, dataclasses).
"""
from enum import Enum, auto
from dataclasses import dataclass


class TokenType(Enum):
    # Keywords
    PATIENT = auto()
    DRUG = auto()
    INFUSION = auto()
    WEIGHT = auto()
    MAX_RATE = auto()
    FOR = auto()
    USING = auto()
    AT = auto()
    IF = auto()
    THEN = auto()
    ELSE = auto()
    REPEAT = auto()
    EVERY = auto()
    UNTIL = auto()
    # Phase 3: cumulative dose bounds, per-administration duration, drug interactions
    MAX_TOTAL = auto()
    OVER = auto()
    INTERACTION = auto()
    WITH = auto()
    LIMIT = auto()

    # Literals
    IDENT = auto()
    NUMBER = auto()
    UNIT = auto()

    # Symbols
    LBRACE = auto()      # {
    RBRACE = auto()      # }
    COLON = auto()        # :
    SEMI = auto()         # ;
    SLASH = auto()        # /
    COMMA = auto()        # ,

    # Comparators (Phase 2: weight-tiered conditionals)
    GT = auto()            # >
    GTE = auto()           # >=
    LT = auto()            # <
    LTE = auto()           # <=
    EQEQ = auto()          # ==

    EOF = auto()


@dataclass(frozen=True)
class Token:
    type: TokenType
    lexeme: str
    line: int
    col: int

    def __repr__(self) -> str:
        return f"Token({self.type.name}, {self.lexeme!r}, {self.line}:{self.col})"
