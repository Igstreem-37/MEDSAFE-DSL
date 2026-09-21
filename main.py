"""
main.py
Command-line driver for the MEDSAFE-DSL compiler front-end.
Pipeline: source (.smed) -> Lexer -> Parser -> AST -> SemanticAnalyzer
          -> SymbolTable + diagnostic report.
"""
import argparse
import sys

from lexer import Lexer, LexicalError
from parser import Parser, SyntaxErrorMEDSAFE
from semantic import SemanticAnalyzer, SemanticError, ReferenceError_
from symbol_table import SymbolCollisionError


def run(path: str, show_tokens: bool, show_ast: bool, show_symtab: bool, quiet_stages: bool = False) -> int:
    stage_mode = not (show_tokens or show_ast or show_symtab) and not quiet_stages

    with open(path, "r") as f:
        source = f.read()

    try:
        tokens = Lexer(source).tokenize()
    except LexicalError as e:
        print(e)
        return 1
    if stage_mode:
        print("LEXICAL ANALYSIS      OK")

    if show_tokens:
        for t in tokens:
            print(t)

    try:
        program = Parser(tokens).parse_program()
    except SyntaxErrorMEDSAFE as e:
        print(e)
        return 1
    if stage_mode:
        print("SYNTAX ANALYSIS       OK")
        print("AST CONSTRUCTION      OK")

    if show_ast:
        print(program.pretty())

    try:
        analyzer = SemanticAnalyzer(program)
        symtab = analyzer.analyze()
    except (SymbolCollisionError, ReferenceError_, SemanticError) as e:
        print(e)
        return 1
    if stage_mode:
        print("SYMBOL TABLE          OK")
        print("SEMANTIC ANALYSIS     OK")

    if show_symtab:
        print(f"{'NAME':<12}{'KIND':<10}{'TYPE':<28}{'BASELINE':<10}{'LINE:COL'}")
        for entry in symtab.all_entries():
            print(f"{entry.name:<12}{entry.kind:<10}{entry.inferred_type:<28}"
                  f"{entry.baseline_value:<10}{entry.declared_at[0]}:{entry.declared_at[1]}")

    if stage_mode:
        print("DOMAIN STATIC ANALYSIS OK  (rate-limit + unit normalization)")

    print(f"\n[Diagnostic Report] {len(analyzer.diagnostics)} infusion rule(s) statically verified:")
    for d in analyzer.diagnostics:
        print(f"  INFUSION {d.infusion}: {d.normalized_rate_mg_per_hr:.3f} mg/hr <= "
              f"{d.normalized_limit_mg_per_hr:.3f} mg/hr  -> {d.verdict}")

    if stage_mode:
        print("COMPILATION SUCCESSFUL")
    else:
        print("Compilation successful. No static safety violations detected.")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(prog="main.py", description="MEDSAFE-DSL compiler front-end")
    parser.add_argument("source", help="path to a .smed source file")
    parser.add_argument("--tokens", action="store_true", help="print the lexical token stream")
    parser.add_argument("--ast", action="store_true", help="print the parsed AST")
    parser.add_argument("--symtab", action="store_true", help="print the resolved symbol table")
    args = parser.parse_args()
    sys.exit(run(args.source, args.tokens, args.ast, args.symtab))
