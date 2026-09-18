"""
semantic.py
Semantic analysis pass for MEDSAFE-DSL, split into two stages:

  1. Declaration binding  - walks PatientDecl / DrugDecl nodes, inserts them
     into the SymbolTable, and rejects identifier collisions.
  2. Domain static analysis - walks InfusionDecl nodes, resolves references
     to previously bound patients/drugs, normalizes both the drug's
     max_rate and the infusion's requested rate to a canonical unit basis
     (mg/hr), and statically proves (or disproves) that the requested rate
     is within the drug's declared safety bound.

This is the pass referenced in the report as "Algorithm 4: Domain Static
Analysis (Rate-Limit Normalization)".
"""
from dataclasses import dataclass
from ast_nodes import Program, Quantity
from symbol_table import SymbolTable, SymbolCollisionError

# Canonical basis for rate comparison: milligrams per hour (mg/hr).
_MASS_TO_MG = {"mg": 1.0, "mcg": 0.001, "g": 1000.0}
_TIME_TO_HR = {"hr": 1.0, "min": 1.0 / 60.0}


class SemanticError(Exception):
    def __init__(self, message: str, line: int, col: int):
        super().__init__(f"[Domain Semantic Error] {message} at line {line}, column {col}")
        self.line = line
        self.col = col


class ReferenceError_(Exception):
    def __init__(self, message: str, line: int, col: int):
        super().__init__(f"[Semantic Error] {message} at line {line}, column {col}")
        self.line = line
        self.col = col


@dataclass
class Diagnostic:
    infusion: str
    normalized_rate_mg_per_hr: float
    normalized_limit_mg_per_hr: float
    verdict: str   # "SAFE" or "UNSAFE"


def normalize_to_mg_per_hr(q: Quantity) -> float:
    """Unit normalization: converts a mass/time Quantity to mg/hr."""
    if q.unit not in _MASS_TO_MG:
        raise SemanticError(f"unrecognized mass unit {q.unit!r}", 0, 0)
    if q.rate_unit not in _TIME_TO_HR:
        raise SemanticError(f"unrecognized time unit {q.rate_unit!r}", 0, 0)
    mg = q.value * _MASS_TO_MG[q.unit]
    per_hr = mg / _TIME_TO_HR[q.rate_unit]
    return per_hr


class SemanticAnalyzer:
    def __init__(self, program: Program):
        self.program = program
        self.symtab = SymbolTable()
        self.diagnostics: list[Diagnostic] = []

    def analyze(self) -> SymbolTable:
        self._bind_declarations()
        self._check_infusions()
        return self.symtab

    # ---- stage 1: declaration binding --------------------------------
    def _bind_declarations(self) -> None:
        for p in self.program.patients:
            self.symtab.insert(
                p.name, "patient",
                f"Patient(weight: {p.weight.unit})",
                p.weight.value, p.line, p.col,
            )
        for d in self.program.drugs:
            self.symtab.insert(
                d.name, "drug",
                f"Drug(max_rate: {d.max_rate.unit}/{d.max_rate.rate_unit})",
                d.max_rate.value, d.line, d.col,
            )

    # ---- stage 2: domain static analysis ------------------------------
    def _check_infusions(self) -> None:
        for inf in self.program.infusions:
            patient_entry = self.symtab.lookup(inf.patient)
            if patient_entry is None or patient_entry.kind != "patient":
                raise ReferenceError_(
                    f"infusion {inf.name!r} references undeclared patient {inf.patient!r}",
                    inf.line, inf.col,
                )
            drug_entry = self.symtab.lookup(inf.drug)
            if drug_entry is None or drug_entry.kind != "drug":
                raise ReferenceError_(
                    f"infusion {inf.name!r} references undeclared drug {inf.drug!r}",
                    inf.line, inf.col,
                )

            drug_decl = next(d for d in self.program.drugs if d.name == inf.drug)
            normalized_rate = normalize_to_mg_per_hr(inf.rate)
            normalized_limit = normalize_to_mg_per_hr(drug_decl.max_rate)

            if normalized_rate > normalized_limit:
                raise SemanticError(
                    f"infusion {inf.name!r} requests {inf.rate.value} {inf.rate.unit}/"
                    f"{inf.rate.rate_unit} ({normalized_rate:.3f} mg/hr normalized) which "
                    f"exceeds max_rate {drug_decl.max_rate.value} {drug_decl.max_rate.unit}/"
                    f"{drug_decl.max_rate.rate_unit} ({normalized_limit:.3f} mg/hr normalized) "
                    f"for drug {inf.drug!r}",
                    inf.line, inf.col,
                )

            self.diagnostics.append(Diagnostic(inf.name, normalized_rate, normalized_limit, "SAFE"))
