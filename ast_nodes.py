"""
ast_nodes.py
Typed Abstract Syntax Tree node hierarchy for MEDSAFE-DSL, implemented with
dataclasses per the zero-dependency implementation policy.
"""
from dataclasses import dataclass, field


@dataclass
class Quantity:
    value: float
    unit: str            # e.g. "kg"
    rate_unit: str | None = None   # e.g. "hr" when the quantity is a rate like mg/hr


@dataclass
class PatientDecl:
    name: str
    weight: Quantity
    line: int
    col: int


@dataclass
class DrugDecl:
    name: str
    max_rate: Quantity
    line: int
    col: int


@dataclass
class InfusionDecl:
    name: str
    patient: str
    drug: str
    rate: Quantity
    line: int
    col: int


@dataclass
class Program:
    patients: list[PatientDecl] = field(default_factory=list)
    drugs: list[DrugDecl] = field(default_factory=list)
    infusions: list[InfusionDecl] = field(default_factory=list)

    def pretty(self, indent: int = 0) -> str:
        pad = "  " * indent
        lines = [f"{pad}Program"]
        for p in self.patients:
            lines.append(f"{pad}  PatientDecl(name={p.name!r})")
            lines.append(f"{pad}    Quantity({p.weight.value} {p.weight.unit})")
        for d in self.drugs:
            lines.append(f"{pad}  DrugDecl(name={d.name!r})")
            lines.append(f"{pad}    Quantity({d.max_rate.value} {d.max_rate.unit}/{d.max_rate.rate_unit})")
        for i in self.infusions:
            lines.append(f"{pad}  InfusionDecl(name={i.name!r}, patient={i.patient!r}, drug={i.drug!r})")
            lines.append(f"{pad}    Quantity({i.rate.value} {i.rate.unit}/{i.rate.rate_unit})")
        return "\n".join(lines)
