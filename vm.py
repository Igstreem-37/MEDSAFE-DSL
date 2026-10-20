"""
vm.py
MEDSAFE virtual machine (Phase 3): loads and executes the binary bytecode
produced by bytecode.py, then runs a discrete-event simulation of the
verified protocol over simulated time with a runtime safety monitor.

Execution has two phases:

1. LOAD phase -- the VM walks the instruction stream once. It does NOT trust
   the compiler: every CHECK_* instruction is re-verified against the limits
   declared by the DEF_* instructions in the same stream. Tampered or
   corrupted bytecode (e.g. a rate edited in a hex editor) is therefore
   rejected with a VMError before any simulation starts.

2. SIMULATION phase -- a discrete-event simulation. Continuous INFUSE
   instructions run for the whole horizon; SCHEDULE instructions start and stop
   at their administration times. At every event the monitor recomputes, per
   patient and drug, the concurrent rate, and tracks the cumulative dose.
   This catches hazards that per-declaration static analysis cannot see, for
   example a continuous infusion and a scheduled bolus of the same drug that
   overlap in time and together exceed the drug's max_rate.

Runtime alarms are recorded (not raised): a monitor must report every
violation, not stop at the first one.
"""
import re
import time
from dataclasses import dataclass, field

from ir import Instruction

_MASS_TO_MG = {"mg": 1.0, "mcg": 0.001, "g": 1000.0}
_TIME_TO_HR = {"hr": 1.0, "min": 1.0 / 60.0}
_QTY = re.compile(r"^([0-9]*\.?[0-9]+)([A-Za-z]+)(?:/([A-Za-z]+))?$")
_EPS = 1e-9


class VMError(Exception):
    """Raised when bytecode fails load-time verification or is malformed."""


def _parse_qty(text: str, where: str) -> tuple[float, str, str | None]:
    m = _QTY.match(str(text))
    if not m:
        raise VMError(f"{where}: cannot parse quantity {text!r}")
    return float(m.group(1)), m.group(2), m.group(3)


def _mass_mg(text: str, where: str) -> float:
    value, unit, _ = _parse_qty(text, where)
    if unit not in _MASS_TO_MG:
        raise VMError(f"{where}: unknown mass unit {unit!r}")
    return value * _MASS_TO_MG[unit]


def _rate_mg_hr(text: str, where: str) -> float:
    value, unit, per = _parse_qty(text, where)
    if unit not in _MASS_TO_MG or per not in _TIME_TO_HR:
        raise VMError(f"{where}: unknown rate unit in {text!r}")
    return value * _MASS_TO_MG[unit] / _TIME_TO_HR[per]


@dataclass
class Alarm:
    time_hr: float
    kind: str          # RATE_EXCEEDED | TOTAL_EXCEEDED | INTERACTION_EXCEEDED
    message: str


@dataclass
class Segment:
    t0: float
    t1: float
    active: list                 # labels of the infusions/administrations running
    rates: dict                  # (patient, drug) -> mg/hr during the segment
    cumulative: dict             # (patient, drug) -> mg delivered by t1


@dataclass
class SimulationResult:
    horizon_hr: float
    segments: list = field(default_factory=list)
    alarms: list = field(default_factory=list)
    cumulative: dict = field(default_factory=dict)
    peak_rate: dict = field(default_factory=dict)
    instructions_executed: int = 0
    load_seconds: float = 0.0
    sim_seconds: float = 0.0

    @property
    def status(self) -> str:
        return "ALARM" if self.alarms else "SAFE"


@dataclass
class _Admin:
    label: str
    patient: str
    drug: str
    rate: float
    start: float
    end: float


class MedsafeVM:
    def __init__(self, instrs: list[Instruction], horizon_hr: float | None = None):
        self.instrs = instrs
        self.horizon_hr = horizon_hr
        self.patients: dict[str, float] = {}
        self.drugs: dict[str, dict] = {}
        self.interactions: dict[frozenset, float] = {}
        self.continuous: list[tuple] = []          # (label, patient, drug, rate, duration_hr or None)
        self.schedules: list[dict] = []
        self.load_log: list[str] = []
        self._loaded = False

    # ------------------------------------------------------------------
    # Phase 1: load + re-verify
    # ------------------------------------------------------------------
    def load(self) -> None:
        t0 = time.perf_counter()
        executed = 0
        halted = False
        for ins in self.instrs:
            where = f"instruction {ins.addr:04d} ({ins.opcode})"
            op, a = ins.opcode, ins.operands
            executed += 1
            if op == "DEF_PATIENT":
                w_value, w_unit, _ = _parse_qty(a["weight"], where)
                if w_unit != "kg":
                    raise VMError(f"{where}: patient weight must be in kg, got {w_unit!r}")
                self.patients[a["name"]] = w_value
            elif op == "DEF_DRUG":
                self.drugs[a["name"]] = {
                    "max_rate": _rate_mg_hr(a["max_rate"], where),
                    "max_total": _mass_mg(a["max_total"], where) if "max_total" in a else None,
                }
            elif op == "DEF_INTERACT":
                self._require_drug(a["drug_a"], where)
                self._require_drug(a["drug_b"], where)
                self.interactions[frozenset((a["drug_a"], a["drug_b"]))] = _rate_mg_hr(a["limit"], where)
            elif op == "WEIGHT_CMP":
                self._require_patient(a["patient"], where)
            elif op == "CHECK_RATE":
                self._verify_rate(a, where)
            elif op == "INFUSE":
                self._require_patient(a["patient"], where)
                self._require_drug(a["drug"], where)
                dur = float(a["duration_hr"]) if "duration_hr" in a else None
                self.continuous.append((a["subject"], a["patient"], a["drug"],
                                        _rate_mg_hr(a["rate"], where), dur))
            elif op == "SCHEDULE":
                self._require_patient(a["patient"], where)
                self._require_drug(a["drug"], where)
                self.schedules.append({
                    "label": a["subject"], "patient": a["patient"], "drug": a["drug"],
                    "rate": _rate_mg_hr(a["rate"], where),
                    "interval": float(a["interval_hr"]), "until": float(a["until_hr"]),
                    "duration": float(a["duration_hr"]), "count": int(a["count"]),
                })
            elif op == "CHECK_TOTAL":
                self._verify_total(a, where)
            elif op == "CHECK_INTERACT":
                self._verify_interact(a, where)
            elif op == "LOOP_META":
                pass
            elif op == "HALT":
                halted = True
                self.load_log.append(f"{ins.addr:04d} HALT         load phase complete")
                break
            else:
                raise VMError(f"{where}: unknown opcode")
            if op.startswith("CHECK"):
                self.load_log.append(f"{ins.addr:04d} {op:<14} re-verified OK")
        if not halted:
            raise VMError("bytecode has no HALT instruction (truncated program)")
        self._executed = executed
        self._load_seconds = time.perf_counter() - t0
        self._loaded = True

    def _require_patient(self, name: str, where: str) -> None:
        if name not in self.patients:
            raise VMError(f"{where}: references patient {name!r} that was never defined")

    def _require_drug(self, name: str, where: str) -> None:
        if name not in self.drugs:
            raise VMError(f"{where}: references drug {name!r} that was never defined")

    def _verify_rate(self, a: dict, where: str) -> None:
        self._require_patient(a["patient"], where)
        self._require_drug(a["drug"], where)
        rate = _rate_mg_hr(a["rate"], where)
        limit = self.drugs[a["drug"]]["max_rate"]       # authoritative: the DEF_DRUG limit
        if a.get("verdict") != "SAFE":
            raise VMError(f"{where}: bytecode carries verdict {a.get('verdict')!r}, expected SAFE")
        if rate > limit + _EPS:
            raise VMError(
                f"{where}: load-time verification FAILED -- {a['subject']!r} requests "
                f"{rate:.3f} mg/hr but drug {a['drug']!r} is limited to {limit:.3f} mg/hr "
                f"(bytecode tampered or corrupted)")

    def _verify_total(self, a: dict, where: str) -> None:
        self._require_patient(a["patient"], where)
        self._require_drug(a["drug"], where)
        limit = self.drugs[a["drug"]]["max_total"]
        if limit is None:
            raise VMError(f"{where}: CHECK_TOTAL for drug {a['drug']!r} which declares no MAX_TOTAL")
        total = _mass_mg(a["total"], where)
        if total > limit + _EPS:
            raise VMError(f"{where}: load-time verification FAILED -- cumulative dose {total:.3f} mg "
                          f"exceeds MAX_TOTAL {limit:.3f} mg for drug {a['drug']!r}")

    def _verify_interact(self, a: dict, where: str) -> None:
        key = frozenset((a["drug_a"], a["drug_b"]))
        if key not in self.interactions:
            raise VMError(f"{where}: CHECK_INTERACT without a matching DEF_INTERACT")
        combined = _rate_mg_hr(a["combined"], where)
        limit = self.interactions[key]
        if combined > limit + _EPS:
            raise VMError(f"{where}: load-time verification FAILED -- combined rate {combined:.3f} mg/hr "
                          f"exceeds INTERACTION limit {limit:.3f} mg/hr")

    # ------------------------------------------------------------------
    # Phase 2: discrete-event simulation with a runtime monitor
    # ------------------------------------------------------------------
    def simulate(self) -> SimulationResult:
        if not self._loaded:
            raise VMError("simulate() called before load()")
        t_start = time.perf_counter()

        horizon = self.horizon_hr
        if horizon is None:
            spans = [s["until"] for s in self.schedules] + \
                    [c[4] for c in self.continuous if c[4] is not None]
            horizon = max(spans, default=24.0)
        result = SimulationResult(horizon_hr=horizon)

        admins: list[_Admin] = []
        for (label, patient, drug, rate, dur) in self.continuous:
            if dur is not None:                      # Phase 3.2: bounded infusion [0, dur)
                admins.append(_Admin(label, patient, drug, rate, 0.0, min(dur, horizon)))
        for s in self.schedules:
            for k in range(s["count"]):
                start = k * s["interval"]
                if start >= horizon - _EPS:
                    break
                end = min(start + s["duration"], horizon)
                admins.append(_Admin(f"{s['label']}#{k + 1}", s["patient"], s["drug"],
                                     s["rate"], start, end))

        # Event times: horizon bounds plus every administration start/end.
        times = {0.0, horizon}
        for ad in admins:
            times.add(round(ad.start, 9))
            times.add(round(ad.end, 9))
        times = sorted(t for t in times if 0.0 <= t <= horizon + _EPS)

        cumulative: dict = {}
        total_alarmed: set = set()
        active_violations: set = set()

        for t0, t1 in zip(times, times[1:]):
            dt = t1 - t0
            if dt <= _EPS:
                continue
            rates: dict = {}
            labels: list = []
            for (label, patient, drug, rate, dur) in self.continuous:
                if dur is not None:
                    continue                         # bounded infusions run as admins
                rates[(patient, drug)] = rates.get((patient, drug), 0.0) + rate
                labels.append(label)
            for ad in admins:
                if ad.start - _EPS <= t0 and t0 < ad.end - _EPS:
                    rates[(ad.patient, ad.drug)] = rates.get((ad.patient, ad.drug), 0.0) + ad.rate
                    labels.append(ad.label)

            # -- runtime monitor: concurrent per-drug rate --------------------
            now_violating: set = set()
            for (patient, drug), rate in rates.items():
                limit = self.drugs[drug]["max_rate"]
                key = ("RATE", patient, drug)
                if rate > limit + _EPS:
                    now_violating.add(key)
                    if key not in active_violations:
                        result.alarms.append(Alarm(
                            t0, "RATE_EXCEEDED",
                            f"t={t0:g}hr: concurrent rate of {drug!r} for {patient!r} is "
                            f"{rate:.3f} mg/hr, exceeding max_rate {limit:.3f} mg/hr "
                            f"(running: {', '.join(labels)})"))
                prev = result.peak_rate.get((patient, drug), 0.0)
                result.peak_rate[(patient, drug)] = max(prev, rate)

            # -- runtime monitor: drug interactions ----------------------------
            for pair, limit in self.interactions.items():
                da, db = tuple(pair)
                for patient in self.patients:
                    ra, rb = rates.get((patient, da), 0.0), rates.get((patient, db), 0.0)
                    if ra > 0 and rb > 0:
                        key = ("INTERACT", patient, tuple(sorted(pair)))
                        if ra + rb > limit + _EPS:
                            now_violating.add(key)
                            if key not in active_violations:
                                result.alarms.append(Alarm(
                                    t0, "INTERACTION_EXCEEDED",
                                    f"t={t0:g}hr: {da!r} + {db!r} for {patient!r} combined "
                                    f"{ra + rb:.3f} mg/hr exceeds INTERACTION limit {limit:.3f} mg/hr"))
            active_violations = now_violating

            # -- cumulative dose ------------------------------------------------
            for (patient, drug), rate in rates.items():
                before = cumulative.get((patient, drug), 0.0)
                after = before + rate * dt
                cumulative[(patient, drug)] = after
                cap = self.drugs[drug]["max_total"]
                if cap is not None and after > cap + _EPS and (patient, drug) not in total_alarmed:
                    total_alarmed.add((patient, drug))
                    crossing = t0 + (cap - before) / rate if rate > 0 else t0
                    result.alarms.append(Alarm(
                        crossing, "TOTAL_EXCEEDED",
                        f"t={crossing:.3f}hr: cumulative dose of {drug!r} for {patient!r} crosses "
                        f"MAX_TOTAL {cap:.3f} mg (reaches {after:.3f} mg by t={t1:g}hr)"))

            result.segments.append(Segment(t0, t1, labels, dict(rates), dict(cumulative)))

        result.alarms.sort(key=lambda al: al.time_hr)
        result.cumulative = cumulative
        result.instructions_executed = self._executed
        result.load_seconds = self._load_seconds
        result.sim_seconds = time.perf_counter() - t_start
        return result

    def run(self) -> SimulationResult:
        self.load()
        return self.simulate()


def format_trace(result: SimulationResult) -> str:
    """Human-readable execution trace of a simulation (one row per event interval)."""
    lines = [f"{'t0(hr)':>7} {'t1(hr)':>7}  {'rates (mg/hr)':<38} {'cumulative (mg)':<30} active"]
    for seg in result.segments:
        rates = ", ".join(f"{d}={r:.1f}" for (_, d), r in sorted(seg.rates.items())) or "-"
        cum = ", ".join(f"{d}={c:.1f}" for (_, d), c in sorted(seg.cumulative.items())) or "-"
        lines.append(f"{seg.t0:>7.2f} {seg.t1:>7.2f}  {rates:<38} {cum:<30} {len(seg.active)}")
    return "\n".join(lines)
