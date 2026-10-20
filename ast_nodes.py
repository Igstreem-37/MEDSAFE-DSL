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
class DrugBinding:
    """One (drug, rate) pair within an INFUSION — a plain infusion has exactly
    one binding; a multi-drug (co-administered) infusion has more than one."""
    drug: str
    rate: Quantity


@dataclass
class ConditionalBinding:
    """A weight-tiered dose: IF WEIGHT <cmp> threshold THEN rate ELSE rate.
    Because a patient's weight is a compile-time constant in MEDSAFE-DSL, the
    branch is resolved statically during semantic analysis (see semantic.py)."""
    drug: str
    comparator: str          # one of '>', '>=', '<', '<=', '=='
    threshold: Quantity      # e.g. 50 kg
    then_rate: Quantity
    else_rate: Quantity


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
    # Phase 3: optional cumulative bound (e.g. 200 mg) over a patient's whole
    # protocol. None means "no cumulative limit declared" for this drug.
    max_total: Quantity | None = None


@dataclass
class InteractionDecl:
    """Phase 3: INTERACTION a WITH b LIMIT <rate>; -- the combined concurrent
    infusion rate of drugs a and b for one patient must not exceed `limit`.
    A limit of 0 declares the pair contraindicated."""
    drug_a: str
    drug_b: str
    limit: Quantity
    line: int
    col: int


@dataclass
class InfusionDecl:
    """Either a plain/multi-drug infusion (bindings non-empty, conditional is
    None) or a weight-tiered conditional infusion (conditional is set,
    bindings is empty). Exactly one of the two is populated by the parser."""
    name: str
    patient: str
    line: int
    col: int
    bindings: list[DrugBinding] = field(default_factory=list)
    conditional: ConditionalBinding | None = None


@dataclass
class RepeatDecl:
    """A scheduled/repeated infusion: the same (patient, drug, rate) applied
    every `interval` until `until` has elapsed. Both bounds are compile-time
    constants, so the exact repetition count is computed statically."""
    name: str
    patient: str
    drug: str
    rate: Quantity
    interval: Quantity       # e.g. 4 hr
    until: Quantity          # e.g. 24 hr
    line: int
    col: int
    # Phase 3: how long each administration lasts (OVER clause). None means the
    # worst case -- each administration lasts the whole interval (continuous).
    duration: Quantity | None = None


@dataclass
class Program:
    patients: list[PatientDecl] = field(default_factory=list)
    drugs: list[DrugDecl] = field(default_factory=list)
    infusions: list[InfusionDecl] = field(default_factory=list)
    repeats: list[RepeatDecl] = field(default_factory=list)
    interactions: list[InteractionDecl] = field(default_factory=list)

    def pretty(self, indent: int = 0) -> str:
        pad = "  " * indent
        lines = [f"{pad}Program"]
        for pt in self.patients:
            lines.append(f"{pad}  PatientDecl(name={pt.name!r})")
            lines.append(f"{pad}    Quantity({pt.weight.value} {pt.weight.unit})")
        for d in self.drugs:
            lines.append(f"{pad}  DrugDecl(name={d.name!r})")
            lines.append(f"{pad}    Quantity({d.max_rate.value} {d.max_rate.unit}/{d.max_rate.rate_unit})")
            if d.max_total is not None:
                lines.append(f"{pad}    MAX_TOTAL Quantity({d.max_total.value} {d.max_total.unit})")
        for ix in self.interactions:
            lines.append(f"{pad}  InteractionDecl({ix.drug_a!r} WITH {ix.drug_b!r})")
            lines.append(f"{pad}    LIMIT Quantity({ix.limit.value} {ix.limit.unit}/{ix.limit.rate_unit})")
        for i in self.infusions:
            if i.conditional:
                c = i.conditional
                lines.append(f"{pad}  InfusionDecl(name={i.name!r}, patient={i.patient!r}, drug={c.drug!r}) [conditional]")
                lines.append(f"{pad}    IF WEIGHT {c.comparator} {c.threshold.value}{c.threshold.unit}")
                lines.append(f"{pad}    THEN Quantity({c.then_rate.value} {c.then_rate.unit}/{c.then_rate.rate_unit})")
                lines.append(f"{pad}    ELSE Quantity({c.else_rate.value} {c.else_rate.unit}/{c.else_rate.rate_unit})")
            else:
                drugs_str = ", ".join(b.drug for b in i.bindings)
                lines.append(f"{pad}  InfusionDecl(name={i.name!r}, patient={i.patient!r}, drugs=[{drugs_str}])")
                for b in i.bindings:
                    lines.append(f"{pad}    Quantity({b.rate.value} {b.rate.unit}/{b.rate.rate_unit})  [{b.drug}]")
        for r in self.repeats:
            lines.append(f"{pad}  RepeatDecl(name={r.name!r}, patient={r.patient!r}, drug={r.drug!r})")
            lines.append(f"{pad}    Quantity({r.rate.value} {r.rate.unit}/{r.rate.rate_unit}) EVERY {r.interval.value}{r.interval.unit} UNTIL {r.until.value}{r.until.unit}"
                         + (f" OVER {r.duration.value}{r.duration.unit}" if r.duration else ""))
        return "\n".join(lines)
