"""
semantic.py
Semantic analysis pass for MEDSAFE-DSL, split into two stages:

  1. Declaration binding  - walks PatientDecl / DrugDecl nodes, inserts them
     into the SymbolTable, and rejects identifier collisions.
  2. Domain static analysis - walks InfusionDecl and RepeatDecl nodes,
     resolves references to previously bound patients/drugs, normalizes
     units to a canonical basis, and statically proves (or disproves) that
     every requested infusion rate is within its drug's declared safety
     bound. This stage also:
       - loops over every (drug, rate) binding in a multi-drug infusion;
       - for a weight-tiered conditional infusion, evaluates the condition
         against the patient's (compile-time-constant) declared weight and
         resolves the THEN/ELSE branch statically, then checks only the
         chosen rate;
       - for a REPEAT declaration, validates that the interval and total
         duration are positive and consistent, and computes the exact
         number of repetitions (a compile-time-constant loop trip count).

This is the pass referenced in the Phase 1 report as "Algorithm 4: Domain
Static Analysis (Rate-Limit Normalization)", extended in Phase 2 for
multi-drug, conditional, and repeat constructs.
"""
import operator
import math
from dataclasses import dataclass, field
from ast_nodes import Program, Quantity
from symbol_table import SymbolTable, SymbolCollisionError

# Canonical basis for rate comparison: milligrams per hour (mg/hr).
_MASS_TO_MG = {"mg": 1.0, "mcg": 0.001, "g": 1000.0}
_TIME_TO_HR = {"hr": 1.0, "min": 1.0 / 60.0}

_COMPARATORS = {
    ">": operator.gt, ">=": operator.ge,
    "<": operator.lt, "<=": operator.le,
    "==": operator.eq,
}


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
class RateCheck:
    """One statically-verified rate check. kind is 'infusion', 'conditional',
    or 'repeat'. `subject` is a human-readable label for the diagnostic
    report and for IR generation (ir.py consumes this list directly)."""
    subject: str
    kind: str
    patient: str
    drug: str
    rate_mg_per_hr: float
    limit_mg_per_hr: float
    verdict: str = "SAFE"
    detail: dict = field(default_factory=dict)
    line: int = 0          # Phase 3: source location, used by interaction diagnostics
    col: int = 0


@dataclass
class TotalDoseCheck:
    """Phase 3: statically-verified cumulative dose for one (patient, drug)
    pair, summed over every REPEAT schedule for that pair."""
    patient: str
    drug: str
    total_mg: float
    limit_mg: float
    contributors: list
    verdict: str = "SAFE"


@dataclass
class InteractionCheck:
    """Phase 3: statically-verified combined concurrent rate of two interacting
    drugs for one patient (all INFUSION declarations run concurrently from t=0)."""
    patient: str
    drug_a: str
    drug_b: str
    combined_mg_per_hr: float
    limit_mg_per_hr: float
    sources: list
    verdict: str = "SAFE"
    peak_time_hr: float = 0.0     # Phase 3.2: when the combined rate peaks


@dataclass
class ConcurrencyCheck:
    """Phase 3.1: statically-verified peak concurrent rate of ONE drug for one
    patient, summed across every INFUSION / conditional / REPEAT source."""
    patient: str
    drug: str
    peak_mg_per_hr: float
    limit_mg_per_hr: float
    peak_time_hr: float
    sources: list
    verdict: str = "SAFE"


def normalize_mass_to_mg(q: Quantity) -> float:
    """Converts a plain mass quantity (no time component, e.g. '200 mg') to mg."""
    if q.unit not in _MASS_TO_MG:
        raise SemanticError(f"unrecognized mass unit {q.unit!r}", 0, 0)
    return q.value * _MASS_TO_MG[q.unit]


def normalize_to_mg_per_hr(q: Quantity) -> float:
    """Unit normalization: converts a mass/time Quantity to mg/hr."""
    if q.unit not in _MASS_TO_MG:
        raise SemanticError(f"unrecognized mass unit {q.unit!r}", 0, 0)
    if q.rate_unit not in _TIME_TO_HR:
        raise SemanticError(f"unrecognized time unit {q.rate_unit!r}", 0, 0)
    mg = q.value * _MASS_TO_MG[q.unit]
    per_hr = mg / _TIME_TO_HR[q.rate_unit]
    return per_hr


def normalize_duration_to_hr(q: Quantity) -> float:
    """Converts a plain duration (no mass component, e.g. '4 hr') to hours."""
    if q.unit not in _TIME_TO_HR:
        raise SemanticError(f"unrecognized time unit {q.unit!r}", 0, 0)
    return q.value * _TIME_TO_HR[q.unit]


class SemanticAnalyzer:
    def __init__(self, program: Program):
        self.program = program
        self.symtab = SymbolTable()
        self.checks: list[RateCheck] = []
        # Backward-compatible alias: Phase 1 code/tests referred to this
        # list as `diagnostics`. Phase 2 extends it to cover every check
        # kind (infusion / conditional / repeat) via RateCheck.
        self.diagnostics = self.checks
        # Phase 3 results
        self.total_checks: list[TotalDoseCheck] = []
        self.interaction_checks: list[InteractionCheck] = []
        # Phase 3.1 result
        self.concurrency_checks: list[ConcurrencyCheck] = []

    def analyze(self) -> SymbolTable:
        self._bind_declarations()
        self._check_infusions()
        self._check_repeats()
        self._check_concurrent_rates()
        self._check_cumulative()
        self._check_interactions()
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

    def _require_patient(self, name: str, owner: str, line: int, col: int):
        entry = self.symtab.lookup(name)
        if entry is None or entry.kind != "patient":
            raise ReferenceError_(f"{owner} references undeclared patient {name!r}", line, col)
        return entry

    def _require_drug(self, name: str, owner: str, line: int, col: int):
        entry = self.symtab.lookup(name)
        if entry is None or entry.kind != "drug":
            raise ReferenceError_(f"{owner} references undeclared drug {name!r}", line, col)
        return next(d for d in self.program.drugs if d.name == name)

    def _check_rate_against_limit(self, subject: str, kind: str, patient: str,
                                   drug_decl, rate: Quantity, line: int, col: int,
                                   detail: dict | None = None) -> RateCheck:
        normalized_rate = normalize_to_mg_per_hr(rate)
        normalized_limit = normalize_to_mg_per_hr(drug_decl.max_rate)
        if normalized_rate > normalized_limit:
            raise SemanticError(
                f"{subject!r} requests {rate.value} {rate.unit}/{rate.rate_unit} "
                f"({normalized_rate:.3f} mg/hr normalized) which exceeds max_rate "
                f"{drug_decl.max_rate.value} {drug_decl.max_rate.unit}/{drug_decl.max_rate.rate_unit} "
                f"({normalized_limit:.3f} mg/hr normalized) for drug {drug_decl.name!r}",
                line, col,
            )
        return RateCheck(subject, kind, patient, drug_decl.name,
                          normalized_rate, normalized_limit, "SAFE", detail or {},
                          line=line, col=col)

    # ---- stage 2a: infusion / multi-drug / conditional checking -------
    def _infusion_duration(self, inf):
        """Phase 3.2: optional OVER on an INFUSION. Returns hours, or None when
        the infusion is unbounded (runs for the whole simulation horizon)."""
        if inf.duration is None:
            return None
        hours = normalize_duration_to_hr(inf.duration)
        if hours <= 0:
            raise SemanticError(f"infusion {inf.name!r} has a non-positive OVER duration",
                                inf.line, inf.col)
        return hours

    def _check_infusions(self) -> None:
        for inf in self.program.infusions:
            self._require_patient(inf.patient, f"infusion {inf.name!r}", inf.line, inf.col)
            inf_hours = self._infusion_duration(inf)

            if inf.conditional is not None:
                c = inf.conditional
                drug_decl = self._require_drug(c.drug, f"infusion {inf.name!r}", inf.line, inf.col)
                patient_entry = self.symtab.lookup(inf.patient)

                if patient_entry.inferred_type != f"Patient(weight: {c.threshold.unit})":
                    raise SemanticError(
                        f"infusion {inf.name!r} compares WEIGHT in {c.threshold.unit!r} but "
                        f"patient {inf.patient!r} declared weight in a different unit",
                        inf.line, inf.col,
                    )
                cmp_fn = _COMPARATORS[c.comparator]
                condition_true = cmp_fn(patient_entry.baseline_value, c.threshold.value)
                chosen_rate = c.then_rate if condition_true else c.else_rate
                branch = "THEN" if condition_true else "ELSE"

                check = self._check_rate_against_limit(
                    inf.name, "conditional", inf.patient, drug_decl, chosen_rate,
                    inf.line, inf.col,
                    detail={
                        "condition": f"WEIGHT {c.comparator} {c.threshold.value}{c.threshold.unit}",
                        "resolved": condition_true,
                        "branch": branch,
                        "duration_hr": inf_hours,
                    },
                )
                self.checks.append(check)
                continue

            for binding in inf.bindings:
                drug_decl = self._require_drug(binding.drug, f"infusion {inf.name!r}", inf.line, inf.col)
                subject = inf.name if len(inf.bindings) == 1 else f"{inf.name}[{binding.drug}]"
                check = self._check_rate_against_limit(
                    subject, "infusion", inf.patient, drug_decl, binding.rate, inf.line, inf.col,
                    detail={"duration_hr": inf_hours},
                )
                self.checks.append(check)

    # ---- stage 2b: repeat / loop-bound checking ------------------------
    def _check_repeats(self) -> None:
        totals: dict = {}   # (patient, drug) -> running cumulative dose, Phase 3
        for rep in self.program.repeats:
            self._require_patient(rep.patient, f"repeat {rep.name!r}", rep.line, rep.col)
            drug_decl = self._require_drug(rep.drug, f"repeat {rep.name!r}", rep.line, rep.col)

            interval_hr = normalize_duration_to_hr(rep.interval)
            until_hr = normalize_duration_to_hr(rep.until)

            if interval_hr <= 0:
                raise SemanticError(f"repeat {rep.name!r} has a non-positive EVERY interval", rep.line, rep.col)
            if until_hr <= 0:
                raise SemanticError(f"repeat {rep.name!r} has a non-positive UNTIL duration", rep.line, rep.col)
            if until_hr < interval_hr:
                raise SemanticError(
                    f"repeat {rep.name!r} UNTIL duration ({until_hr:.3f} hr) is shorter than "
                    f"its EVERY interval ({interval_hr:.3f} hr)",
                    rep.line, rep.col,
                )

            # Compile-time-constant loop trip count: the number of times the
            # infusion is administered within the total duration.
            repeat_count = int(math.floor(until_hr / interval_hr + 1e-9))

            # Phase 3: how long does each administration last? With no OVER
            # clause the worst case is assumed -- each administration runs for
            # the whole interval (i.e. effectively continuous delivery).
            if rep.duration is None:
                duration_hr = interval_hr
            else:
                duration_hr = normalize_duration_to_hr(rep.duration)
                if duration_hr <= 0:
                    raise SemanticError(f"repeat {rep.name!r} has a non-positive OVER duration",
                                        rep.line, rep.col)
                if duration_hr > interval_hr + 1e-9:
                    raise SemanticError(
                        f"repeat {rep.name!r} OVER duration ({duration_hr:.3f} hr) is longer than "
                        f"its EVERY interval ({interval_hr:.3f} hr), so administrations would overlap",
                        rep.line, rep.col,
                    )

            check = self._check_rate_against_limit(
                rep.name, "repeat", rep.patient, drug_decl, rep.rate, rep.line, rep.col,
                detail={
                    "interval_hr": interval_hr,
                    "until_hr": until_hr,
                    "repeat_count": repeat_count,
                    "duration_hr": duration_hr,
                },
            )
            # Phase 3: cumulative dose = rate x duration x number of administrations.
            dose_per_admin_mg = check.rate_mg_per_hr * duration_hr
            total_mg = dose_per_admin_mg * repeat_count
            check.detail["dose_mg"] = dose_per_admin_mg
            check.detail["total_mg"] = total_mg
            self.checks.append(check)

    # ---- shared pulse model (Phase 3.1 / 3.2) ---------------------------
    @staticmethod
    def _pulses(check):
        """Every source is a list of rectangular pulses (start, end, rate_mg_hr,
        label). A REPEAT dose k is [k*EVERY, k*EVERY+OVER). An INFUSION is
        [0, OVER) when it has an OVER clause (Phase 3.2), else [0, infinity)."""
        d = check.detail
        if check.kind == "repeat":
            return [(k * d["interval_hr"], k * d["interval_hr"] + d["duration_hr"],
                     check.rate_mg_per_hr, check.subject) for k in range(d["repeat_count"])]
        end = d.get("duration_hr")
        return [(0.0, math.inf if end is None else end, check.rate_mg_per_hr, check.subject)]

    @staticmethod
    def _active(pulses, t):
        return [p for p in pulses if p[0] <= t + 1e-9 and t + 1e-9 < p[1] - 1e-9]

    # ---- stage 2b': same-drug concurrency (Phase 3.1) --------------------
    def _check_concurrent_rates(self) -> None:
        """Phase 3.1 (extended in 3.2 for bounded infusions). Several
        declarations can deliver the SAME drug to the same patient at once. Each
        is within MAX_RATE alone, but the patient receives their SUM. For every
        (patient, drug) with two or more sources, compute the exact peak of the
        summed rate and prove it is within MAX_RATE. The sum of rectangular
        pulses can only increase when a pulse starts, so it is enough to
        evaluate it at t=0 and at every pulse start."""
        groups: dict = {}   # (patient, drug) -> list of RateCheck
        for c in self.checks:
            groups.setdefault((c.patient, c.drug), []).append(c)

        for (patient, drug), members in groups.items():
            if len(members) < 2:
                continue            # a single source is covered by its own rate check
            limit = members[0].limit_mg_per_hr
            pulses = [p for m in members for p in self._pulses(m)]
            peak, peak_t, peak_who = -1.0, 0.0, []
            for t in sorted({0.0} | {p[0] for p in pulses}):
                active = self._active(pulses, t)
                total = sum(p[2] for p in active)
                if total > peak + 1e-9:
                    peak, peak_t, peak_who = total, t, sorted({p[3] for p in active})
            if peak > limit + 1e-9:
                involved = [m for m in members if m.subject in peak_who]
                later = max(involved, key=lambda m: (m.line, m.col))
                raise SemanticError(
                    f"concurrent infusions of {drug!r} for patient {patient!r} "
                    f"({', '.join(peak_who)}) reach a combined rate of {peak:.3f} mg/hr at "
                    f"t={peak_t:g}hr, exceeding max_rate {limit:.3f} mg/hr",
                    later.line, later.col,
                )
            self.concurrency_checks.append(ConcurrencyCheck(
                patient, drug, peak, limit, peak_t, peak_who))

    # ---- stage 2b'': cumulative dose (Phase 3, extended in 3.2) ----------
    def _check_cumulative(self) -> None:
        """Cumulative dose per (patient, drug) against MAX_TOTAL. REPEAT sources
        contribute rate x OVER x count. Since Phase 3.2 an INFUSION with an OVER
        clause contributes rate x OVER. An INFUSION without OVER has no end, so
        it cannot be totalled statically; the VM monitor covers it."""
        totals: dict = {}
        decls = {d.name: d for d in self.program.drugs}
        for c in self.checks:
            if c.kind == "repeat":
                mg, label = c.detail["total_mg"], "repeat"
            elif c.detail.get("duration_hr") is not None:
                mg, label = c.rate_mg_per_hr * c.detail["duration_hr"], "infusion"
            else:
                continue
            drug_decl = decls[c.drug]
            if drug_decl.max_total is None:
                continue
            key = (c.patient, c.drug)
            limit_mg = normalize_mass_to_mg(drug_decl.max_total)
            prior = totals.setdefault(key, {"total": 0.0, "limit": limit_mg, "who": []})
            prior["total"] += mg
            prior["who"].append(c.subject)
            if prior["total"] > limit_mg + 1e-9:
                raise SemanticError(
                    f"cumulative dose of {c.drug!r} for patient {c.patient!r} reaches "
                    f"{prior['total']:.3f} mg after {label} {c.subject!r} "
                    f"(schedules: {', '.join(prior['who'])}), exceeding MAX_TOTAL "
                    f"{drug_decl.max_total.value} {drug_decl.max_total.unit} "
                    f"({limit_mg:.3f} mg normalized)",
                    c.line, c.col,
                )
        for (patient, drug), info in totals.items():
            self.total_checks.append(TotalDoseCheck(
                patient, drug, info["total"], info["limit"], list(info["who"])))

    # ---- stage 2c: drug-interaction checking (Phase 3, pulse-based in 3.2) --
    def _check_interactions(self) -> None:
        """For every INTERACTION a WITH b LIMIT x and every patient, find the
        exact peak of rate_a(t)+rate_b(t) over the times when BOTH drugs are
        being given, and prove it is within x. Since Phase 3.2 this covers
        continuous infusions, bounded infusions and REPEAT doses alike."""
        by_patient: dict = {}   # patient -> drug -> [RateCheck]
        for c in self.checks:
            by_patient.setdefault(c.patient, {}).setdefault(c.drug, []).append(c)

        for ix in self.program.interactions:
            self._require_drug(ix.drug_a, "interaction", ix.line, ix.col)
            self._require_drug(ix.drug_b, "interaction", ix.line, ix.col)
            if ix.drug_a == ix.drug_b:
                raise SemanticError(
                    f"interaction declares drug {ix.drug_a!r} with itself", ix.line, ix.col)
            limit = normalize_to_mg_per_hr(ix.limit)

            for patient, by_drug in by_patient.items():
                if ix.drug_a not in by_drug or ix.drug_b not in by_drug:
                    continue
                pa = [p for m in by_drug[ix.drug_a] for p in self._pulses(m)]
                pb = [p for m in by_drug[ix.drug_b] for p in self._pulses(m)]
                peak, peak_t, peak_who = -1.0, 0.0, []
                for t in sorted({p[0] for p in pa + pb} | {0.0}):
                    act_a, act_b = self._active(pa, t), self._active(pb, t)
                    if not act_a or not act_b:
                        continue          # the drugs are not being given together
                    combined = sum(p[2] for p in act_a + act_b)
                    if combined > peak + 1e-9:
                        peak, peak_t = combined, t
                        peak_who = sorted({p[3] for p in act_a + act_b})
                if peak < 0:
                    continue
                if peak > limit + 1e-9:
                    members = [m for ds in (by_drug[ix.drug_a], by_drug[ix.drug_b])
                               for m in ds if m.subject in peak_who]
                    later = max(members, key=lambda m: (m.line, m.col))
                    raise SemanticError(
                        f"drugs {ix.drug_a!r} and {ix.drug_b!r} infused concurrently for patient "
                        f"{patient!r} have a combined rate of {peak:.3f} mg/hr "
                        f"(from {', '.join(peak_who)}) at t={peak_t:g}hr, exceeding the "
                        f"INTERACTION limit of {limit:.3f} mg/hr",
                        later.line, later.col,
                    )
                self.interaction_checks.append(InteractionCheck(
                    patient, ix.drug_a, ix.drug_b, peak, limit, peak_who, peak_time_hr=peak_t))
