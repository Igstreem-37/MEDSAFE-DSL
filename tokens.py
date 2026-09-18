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

    EOF = auto()


@dataclass(frozen=True)
class Token:
    type: TokenType
    lexeme: str
    line: int
    col: int

    def __repr__(self) -> str:
        return f"Token({self.type.name}, {self.lexeme!r}, {self.line}:{self.col})"
