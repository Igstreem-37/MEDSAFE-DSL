"""
parser.py
Hand-written LL(1) recursive-descent parser for MEDSAFE-DSL.
Each non-terminal in the EBNF grammar maps to exactly one parsing method;
lookahead is fixed at one token (self.peek()), consistent with the LL(1)
grammar design (see Phase 1 report, Section 8 - Syntax Analysis).
"""
from tokens import Token, TokenType
from ast_nodes import (
    Program, PatientDecl, DrugDecl, InfusionDecl, RepeatDecl, InteractionDecl,
    DrugBinding, ConditionalBinding, Quantity,
)

COMPARATOR_TOKENS = {
    TokenType.GT: ">", TokenType.GTE: ">=",
    TokenType.LT: "<", TokenType.LTE: "<=",
    TokenType.EQEQ: "==",
}


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

    # declaration ::= patient_decl | drug_decl | infusion_decl | repeat_decl
    #                | interaction_decl ;
    def _parse_declaration(self, program: Program) -> None:
        tok = self.peek()
        if tok.type == TokenType.PATIENT:
            program.patients.append(self._parse_patient())
        elif tok.type == TokenType.DRUG:
            program.drugs.append(self._parse_drug())
        elif tok.type == TokenType.INFUSION:
            program.infusions.append(self._parse_infusion())
        elif tok.type == TokenType.REPEAT:
            program.repeats.append(self._parse_repeat())
        elif tok.type == TokenType.INTERACTION:
            program.interactions.append(self._parse_interaction())
        else:
            raise SyntaxErrorMEDSAFE(
                f"expected PATIENT, DRUG, INFUSION, REPEAT or INTERACTION but found "
                f"{tok.type.name} ({tok.lexeme!r})",
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

    # drug_decl ::= "DRUG" IDENT "{" "MAX_RATE" ":" NUMBER UNIT "/" UNIT ";"
    #                [ "MAX_TOTAL" ":" NUMBER UNIT ";" ] "}" ;
    # One token of lookahead (MAX_TOTAL vs RBRACE) decides whether the optional
    # cumulative-dose field is present, so the rule stays LL(1).
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
        max_total = None
        if self.peek().type == TokenType.MAX_TOTAL:
            self.advance()
            self.expect(TokenType.COLON)
            total_value = self.expect(TokenType.NUMBER)
            total_unit = self.expect(TokenType.UNIT)
            self.expect(TokenType.SEMI)
            max_total = Quantity(float(total_value.lexeme), total_unit.lexeme)
        self.expect(TokenType.RBRACE)
        return DrugDecl(
            name=name.lexeme,
            max_rate=Quantity(float(value.lexeme), unit.lexeme, rate_unit.lexeme),
            line=kw.line, col=kw.col,
            max_total=max_total,
        )

    # interaction_decl ::= "INTERACTION" IDENT "WITH" IDENT
    #                      "LIMIT" NUMBER UNIT "/" UNIT ";" ;
    def _parse_interaction(self) -> InteractionDecl:
        kw = self.expect(TokenType.INTERACTION)
        drug_a = self.expect(TokenType.IDENT)
        self.expect(TokenType.WITH)
        drug_b = self.expect(TokenType.IDENT)
        self.expect(TokenType.LIMIT)
        value = self.expect(TokenType.NUMBER)
        unit = self.expect(TokenType.UNIT)
        self.expect(TokenType.SLASH)
        rate_unit = self.expect(TokenType.UNIT)
        self.expect(TokenType.SEMI)
        return InteractionDecl(
            drug_a=drug_a.lexeme, drug_b=drug_b.lexeme,
            limit=Quantity(float(value.lexeme), unit.lexeme, rate_unit.lexeme),
            line=kw.line, col=kw.col,
        )

    # infusion_decl ::= "INFUSION" IDENT "FOR" IDENT "USING" IDENT <infusion_tail> ";"
    #
    # infusion_tail ::= <rate_tail> { "," IDENT <rate_tail> }     -- plain / multi-drug
    #                  | <conditional_tail>                       -- weight-tiered
    #
    # rate_tail        ::= "AT" NUMBER UNIT "/" UNIT
    # conditional_tail ::= "IF" "WEIGHT" comparator NUMBER UNIT
    #                      "THEN" NUMBER UNIT "/" UNIT
    #                      "ELSE" NUMBER UNIT "/" UNIT
    #
    # Disambiguation needs only one token of lookahead: after "USING" IDENT,
    # AT starts a rate binding (plain/multi-drug); IF starts a conditional.
    def _parse_infusion(self) -> InfusionDecl:
        kw = self.expect(TokenType.INFUSION)
        name = self.expect(TokenType.IDENT)
        self.expect(TokenType.FOR)
        patient = self.expect(TokenType.IDENT)
        self.expect(TokenType.USING)
        first_drug = self.expect(TokenType.IDENT)

        if self.peek().type == TokenType.IF:
            conditional = self._parse_conditional_tail(first_drug.lexeme)
            self.expect(TokenType.SEMI)
            return InfusionDecl(name=name.lexeme, patient=patient.lexeme,
                                 line=kw.line, col=kw.col, conditional=conditional)

        bindings = [self._parse_drug_binding(first_drug.lexeme)]
        while self.peek().type == TokenType.COMMA:
            self.advance()
            next_drug = self.expect(TokenType.IDENT)
            bindings.append(self._parse_drug_binding(next_drug.lexeme))
        self.expect(TokenType.SEMI)
        return InfusionDecl(name=name.lexeme, patient=patient.lexeme,
                             line=kw.line, col=kw.col, bindings=bindings)

    def _parse_drug_binding(self, drug_name: str) -> DrugBinding:
        self.expect(TokenType.AT)
        value = self.expect(TokenType.NUMBER)
        unit = self.expect(TokenType.UNIT)
        self.expect(TokenType.SLASH)
        rate_unit = self.expect(TokenType.UNIT)
        return DrugBinding(drug=drug_name, rate=Quantity(float(value.lexeme), unit.lexeme, rate_unit.lexeme))

    def _parse_conditional_tail(self, drug_name: str) -> ConditionalBinding:
        self.expect(TokenType.IF)
        self.expect(TokenType.WEIGHT)
        cmp_tok = self.peek()
        if cmp_tok.type not in COMPARATOR_TOKENS:
            raise SyntaxErrorMEDSAFE(
                f"expected a comparator (>, >=, <, <=, ==) but found {cmp_tok.type.name} ({cmp_tok.lexeme!r})",
                cmp_tok.line, cmp_tok.col,
            )
        self.advance()
        comparator = COMPARATOR_TOKENS[cmp_tok.type]
        thresh_value = self.expect(TokenType.NUMBER)
        thresh_unit = self.expect(TokenType.UNIT)
        self.expect(TokenType.THEN)
        then_value = self.expect(TokenType.NUMBER)
        then_unit = self.expect(TokenType.UNIT)
        self.expect(TokenType.SLASH)
        then_rate_unit = self.expect(TokenType.UNIT)
        self.expect(TokenType.ELSE)
        else_value = self.expect(TokenType.NUMBER)
        else_unit = self.expect(TokenType.UNIT)
        self.expect(TokenType.SLASH)
        else_rate_unit = self.expect(TokenType.UNIT)
        return ConditionalBinding(
            drug=drug_name, comparator=comparator,
            threshold=Quantity(float(thresh_value.lexeme), thresh_unit.lexeme),
            then_rate=Quantity(float(then_value.lexeme), then_unit.lexeme, then_rate_unit.lexeme),
            else_rate=Quantity(float(else_value.lexeme), else_unit.lexeme, else_rate_unit.lexeme),
        )

    # repeat_decl ::= "REPEAT" IDENT "FOR" IDENT "USING" IDENT
    #                 "AT" NUMBER UNIT "/" UNIT
    #                 "EVERY" NUMBER UNIT
    #                 "UNTIL" NUMBER UNIT [ "OVER" NUMBER UNIT ] ";"
    # (OVER vs SEMI is decided with one token of lookahead.)
    def _parse_repeat(self) -> RepeatDecl:
        kw = self.expect(TokenType.REPEAT)
        name = self.expect(TokenType.IDENT)
        self.expect(TokenType.FOR)
        patient = self.expect(TokenType.IDENT)
        self.expect(TokenType.USING)
        drug = self.expect(TokenType.IDENT)
        self.expect(TokenType.AT)
        rate_value = self.expect(TokenType.NUMBER)
        rate_unit = self.expect(TokenType.UNIT)
        self.expect(TokenType.SLASH)
        rate_rate_unit = self.expect(TokenType.UNIT)
        self.expect(TokenType.EVERY)
        interval_value = self.expect(TokenType.NUMBER)
        interval_unit = self.expect(TokenType.UNIT)
        self.expect(TokenType.UNTIL)
        until_value = self.expect(TokenType.NUMBER)
        until_unit = self.expect(TokenType.UNIT)
        duration = None
        if self.peek().type == TokenType.OVER:
            self.advance()
            dur_value = self.expect(TokenType.NUMBER)
            dur_unit = self.expect(TokenType.UNIT)
            duration = Quantity(float(dur_value.lexeme), dur_unit.lexeme)
        self.expect(TokenType.SEMI)
        return RepeatDecl(
            name=name.lexeme, patient=patient.lexeme, drug=drug.lexeme,
            rate=Quantity(float(rate_value.lexeme), rate_unit.lexeme, rate_rate_unit.lexeme),
            interval=Quantity(float(interval_value.lexeme), interval_unit.lexeme),
            until=Quantity(float(until_value.lexeme), until_unit.lexeme),
            line=kw.line, col=kw.col,
            duration=duration,
        )
