"""
parser.py
Hand-written LL(1) recursive-descent parser for MEDSAFE-DSL.
Each non-terminal in the EBNF grammar maps to exactly one parsing method;
lookahead is fixed at one token (self.peek()), consistent with the LL(1)
grammar design (see Phase 1 report, Section 8 - Syntax Analysis).
"""
from tokens import Token, TokenType
from ast_nodes import Program, PatientDecl, DrugDecl, InfusionDecl, Quantity


class SyntaxErrorMEDSAFE(Exception):
    def __init__(self, message: str, line: int, col: int):
        super().__init__(f"[Syntax Error] {message} at line {line}, column {col}")
        self.line = line
        self.col = col


class Parser:
    def __init__(self, tokens: list[Token]):
        self.tokens = tokens
        self.pos = 0

    # ---- helpers ----------------------------------------------------
    def peek(self) -> Token:
        return self.tokens[self.pos]

    def advance(self) -> Token:
        tok = self.tokens[self.pos]
        if tok.type != TokenType.EOF:
            self.pos += 1
        return tok

    def expect(self, ttype: TokenType) -> Token:
        tok = self.peek()
        if tok.type != ttype:
            raise SyntaxErrorMEDSAFE(
                f"expected {ttype.name} but found {tok.type.name} ({tok.lexeme!r})",
                tok.line, tok.col,
            )
        return self.advance()

    # ---- grammar rules ------------------------------------------------
    # program ::= { declaration } ;
    def parse_program(self) -> Program:
        program = Program()
        while self.peek().type != TokenType.EOF:
            self._parse_declaration(program)
        return program

    # declaration ::= patient_decl | drug_decl | infusion_decl ;
    def _parse_declaration(self, program: Program) -> None:
        tok = self.peek()
        if tok.type == TokenType.PATIENT:
            program.patients.append(self._parse_patient())
        elif tok.type == TokenType.DRUG:
            program.drugs.append(self._parse_drug())
        elif tok.type == TokenType.INFUSION:
            program.infusions.append(self._parse_infusion())
        else:
            raise SyntaxErrorMEDSAFE(
                f"expected PATIENT, DRUG or INFUSION but found {tok.type.name} ({tok.lexeme!r})",
                tok.line, tok.col,
            )

    # patient_decl ::= "PATIENT" IDENT "{" "WEIGHT" ":" NUMBER UNIT ";" "}" ;
    def _parse_patient(self) -> PatientDecl:
        kw = self.expect(TokenType.PATIENT)
        name = self.expect(TokenType.IDENT)
        self.expect(TokenType.LBRACE)
        self.expect(TokenType.WEIGHT)
        self.expect(TokenType.COLON)
        value = self.expect(TokenType.NUMBER)
        unit = self.expect(TokenType.UNIT)
        self.expect(TokenType.SEMI)
        self.expect(TokenType.RBRACE)
        return PatientDecl(
            name=name.lexeme,
            weight=Quantity(float(value.lexeme), unit.lexeme),
            line=kw.line, col=kw.col,
        )

    # drug_decl ::= "DRUG" IDENT "{" "MAX_RATE" ":" NUMBER UNIT "/" UNIT ";" "}" ;
    def _parse_drug(self) -> DrugDecl:
        kw = self.expect(TokenType.DRUG)
        name = self.expect(TokenType.IDENT)
        self.expect(TokenType.LBRACE)
        self.expect(TokenType.MAX_RATE)
        self.expect(TokenType.COLON)
        value = self.expect(TokenType.NUMBER)
        unit = self.expect(TokenType.UNIT)
        self.expect(TokenType.SLASH)
        rate_unit = self.expect(TokenType.UNIT)
        self.expect(TokenType.SEMI)
        self.expect(TokenType.RBRACE)
        return DrugDecl(
            name=name.lexeme,
            max_rate=Quantity(float(value.lexeme), unit.lexeme, rate_unit.lexeme),
            line=kw.line, col=kw.col,
        )

    # infusion_decl ::= "INFUSION" IDENT "FOR" IDENT "USING" IDENT
    #                   "AT" NUMBER UNIT "/" UNIT ";" ;
    def _parse_infusion(self) -> InfusionDecl:
        kw = self.expect(TokenType.INFUSION)
        name = self.expect(TokenType.IDENT)
        self.expect(TokenType.FOR)
        patient = self.expect(TokenType.IDENT)
        self.expect(TokenType.USING)
        drug = self.expect(TokenType.IDENT)
        self.expect(TokenType.AT)
        value = self.expect(TokenType.NUMBER)
        unit = self.expect(TokenType.UNIT)
        self.expect(TokenType.SLASH)
        rate_unit = self.expect(TokenType.UNIT)
        self.expect(TokenType.SEMI)
        return InfusionDecl(
            name=name.lexeme,
            patient=patient.lexeme,
            drug=drug.lexeme,
            rate=Quantity(float(value.lexeme), unit.lexeme, rate_unit.lexeme),
            line=kw.line, col=kw.col,
        )
