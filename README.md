# MEDSAFE-DSL — Phase 1 Compiler Front-End

A hand-crafted, zero-dependency compiler front-end for MEDSAFE-DSL, a small
domain-specific language for statically verifying clinical infusion
protocols. Built entirely on the Python 3.10+ standard library
(`dataclasses`, `enum`, `re`, `argparse`, `unittest`) — no Lex, Yacc, ANTLR,
or PLY.

## Requirements

- Python 3.10 or newer (developed and tested on 3.12). No pip packages
  needed.

## Files

| File               | Role                                                        |
|--------------------|--------------------------------------------------------------|
| `tokens.py`        | `TokenType` enum and `Token` dataclass                       |
| `lexer.py`         | Regex-based lexical analyzer                                 |
| `ast_nodes.py`     | AST node dataclasses (Program, PatientDecl, DrugDecl, InfusionDecl, Quantity) |
| `parser.py`        | LL(1) recursive-descent parser                                |
| `symbol_table.py`  | Symbol table with collision detection                        |
| `semantic.py`      | Semantic analysis: declaration binding, reference resolution, unit normalization, rate-limit checking |
| `main.py`          | CLI driver                                                    |
| `valid.smed`       | Sample valid MEDSAFE-DSL program                              |
| `syntax_error.smed`| Sample program with a missing delimiter (syntax error demo)   |
| `semantic_error.smed` | Sample program whose infusion rate exceeds the drug's max_rate (semantic error demo) |
| `tests/`           | 29-case automated test suite (unittest)                       |

## Running the compiler

```bash
# Full pipeline with all introspection flags
python3 main.py valid.smed --tokens --ast --symtab

# Just the token stream
python3 main.py valid.smed --tokens

# Just the AST
python3 main.py valid.smed --ast

# Just the symbol table
python3 main.py valid.smed --symtab

# Trigger the syntax-error diagnostic (missing semicolon)
python3 main.py syntax_error.smed

# Trigger the domain semantic-error diagnostic (rate exceeds max_rate)
python3 main.py semantic_error.smed
```

Exit code is `0` on successful compilation/verification and `1` when a
lexical, syntax, or semantic error is reported.

## Running the test suite

```bash
python3 -m unittest discover -s tests -v
```

This runs all 29 tests across the Lexer, Parser, SymbolTable, and
SemanticAnalyzer modules (unit, integration, and negative/error-path cases)
and should finish with `OK`.

## Writing your own MEDSAFE-DSL programs

Grammar (EBNF):

```
<program>       ::= { <declaration> }
<declaration>   ::= <patient_decl> | <drug_decl> | <infusion_decl>

<patient_decl>  ::= "PATIENT" IDENT "{" "WEIGHT" ":" NUMBER UNIT ";" "}"
<drug_decl>     ::= "DRUG" IDENT "{" "MAX_RATE" ":" NUMBER UNIT "/" UNIT ";" "}"
<infusion_decl> ::= "INFUSION" IDENT
                    "FOR" IDENT
                    "USING" IDENT
                    "AT" NUMBER UNIT "/" UNIT ";"
```

Supported units: `ml, mg, hr, kg, min, mcg, L`. `#` starts a line comment.

## Known Phase 1 limitations (by design)

Control-flow constructs (conditionals, loops) and multi-drug infusion rules
are intentionally out of scope for Phase 1 and are planned for Phase 2 — see
Section 6 (Scope) of the Phase 1 report for how the grammar is designed to
extend without reworking the Lexer/Parser/SymbolTable architecture.
