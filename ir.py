"""
ir.py
Intermediate Representation for MEDSAFE-DSL (Phase 2, extended in Phase 3).

The IR is a flat, linear list of Instruction records (three-address-code
style) generated from an *already verified* AST plus the check lists produced
by SemanticAnalyzer. IR generation performs no checking of its own -- by the
time it runs, every rate, cumulative dose and interaction is already proven
SAFE; the IR simply records that fact in a form the bytecode VM (vm.py) can
re-verify and execute.

Opcodes
    DEF_PATIENT / DEF_DRUG / DEF_INTERACT   declare entities for the VM
    WEIGHT_CMP                              statically resolved weight condition
    CHECK_RATE                              per-dose rate bound (<= max_rate)
    INFUSE                                  start an infusion at t=0 (optional duration_hr)
    SCHEDULE                                a repeated, timed administration
    CHECK_TOTAL                             cumulative dose bound (Phase 3)
    CHECK_INTERACT                          combined-rate bound (Phase 3)
    LOOP_META                               repeat-count metadata (optimizer)
    HALT                                    end of the load phase

REPEAT declarations are lowered naively here -- one CHECK_RATE instruction
per repetition ("loop unrolling") -- deliberately, so that optimizer.py has
a real, visible redundancy to eliminate (see optimizer.py).
"""
from dataclasses import dataclass, field


@dataclass
class Instruction:
    addr: int
    opcode: str
    operands: dict

    def text(self) -> str:
        arg_str = ", ".join(f"{k}={v}" for k, v in self.operands.items())
        return f"{self.addr:04d}  {self.opcode:<14} {arg_str}"


class IRGenerator:
    def __init__(self, program, symtab, checks, total_checks=(), interaction_checks=()):
        self.program = program
        self.symtab = symtab
        self.checks = checks
        self.total_checks = list(total_checks)
        self.interaction_checks = list(interaction_checks)
        self._addr = 0

    def _emit(self, instrs: list[Instruction], opcode: str, **operands) -> None:
        instrs.append(Instruction(self._addr, opcode, operands))
        self._addr += 1

    @staticmethod
    def _infuse_ops(check, rate: str) -> dict:
        ops = {"subject": check.subject, "patient": check.patient,
               "drug": check.drug, "rate": rate}
        dur = check.detail.get("duration_hr")      # Phase 3.2: bounded infusion
        if dur is not None:
            ops["duration_hr"] = f"{dur:.6f}"
        return ops

    def generate(self) -> list[Instruction]:
        instrs: list[Instruction] = []
        self._addr = 0

        for p in self.program.patients:
            self._emit(instrs, "DEF_PATIENT", name=p.name,
                       weight=f"{p.weight.value}{p.weight.unit}")
        for d in self.program.drugs:
            ops = {"name": d.name,
                   "max_rate": f"{d.max_rate.value}{d.max_rate.unit}/{d.max_rate.rate_unit}"}
            if d.max_total is not None:
                ops["max_total"] = f"{d.max_total.value}{d.max_total.unit}"
            self._emit(instrs, "DEF_DRUG", **ops)
        for ix in self.program.interactions:
            self._emit(instrs, "DEF_INTERACT", drug_a=ix.drug_a, drug_b=ix.drug_b,
                       limit=f"{ix.limit.value}{ix.limit.unit}/{ix.limit.rate_unit}")

        for check in self.checks:
            rate = f"{check.rate_mg_per_hr:.3f}mg/hr"
            limit = f"{check.limit_mg_per_hr:.3f}mg/hr"

            if check.kind == "conditional":
                self._emit(instrs, "WEIGHT_CMP", patient=check.patient,
                           condition=check.detail["condition"],
                           resolved=check.detail["resolved"], branch=check.detail["branch"])
                self._emit(instrs, "CHECK_RATE", subject=check.subject, patient=check.patient,
                           drug=check.drug, rate=rate, limit=limit, verdict=check.verdict)
                self._emit(instrs, "INFUSE", **self._infuse_ops(check, rate))

            elif check.kind == "repeat":
                # Naive lowering: unroll the loop into `repeat_count` identical
                # checks, tagged with a shared repeat_group id. optimizer.py
                # collapses these back down.
                count = check.detail["repeat_count"]
                for i in range(1, count + 1):
                    self._emit(instrs, "CHECK_RATE", subject=f"{check.subject}#{i}",
                               patient=check.patient, drug=check.drug, rate=rate,
                               limit=limit, verdict=check.verdict,
                               repeat_group=check.subject)
                # One SCHEDULE per REPEAT gives the VM everything it needs to
                # simulate the administrations over time (Phase 3).
                self._emit(instrs, "SCHEDULE", subject=check.subject, patient=check.patient,
                           drug=check.drug, rate=rate,
                           interval_hr=f"{check.detail['interval_hr']:.6f}",
                           until_hr=f"{check.detail['until_hr']:.6f}",
                           duration_hr=f"{check.detail['duration_hr']:.6f}",
                           count=check.detail["repeat_count"])

            else:  # "infusion" (plain or one binding of a multi-drug infusion)
                self._emit(instrs, "CHECK_RATE", subject=check.subject, patient=check.patient,
                           drug=check.drug, rate=rate, limit=limit, verdict=check.verdict)
                self._emit(instrs, "INFUSE", **self._infuse_ops(check, rate))

        for t in self.total_checks:
            self._emit(instrs, "CHECK_TOTAL", patient=t.patient, drug=t.drug,
                       total=f"{t.total_mg:.3f}mg", limit=f"{t.limit_mg:.3f}mg",
                       verdict=t.verdict)
        for c in self.interaction_checks:
            self._emit(instrs, "CHECK_INTERACT", patient=c.patient, drug_a=c.drug_a,
                       drug_b=c.drug_b, combined=f"{c.combined_mg_per_hr:.3f}mg/hr",
                       limit=f"{c.limit_mg_per_hr:.3f}mg/hr", verdict=c.verdict)

        self._emit(instrs, "HALT")
        return instrs
