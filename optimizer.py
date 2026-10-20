"""
optimizer.py
Phase 2 optimization pass over the naive IR produced by ir.py.

The one real, measurable optimization implemented here is loop-invariant
code motion: ir.py naively unrolls each REPEAT into N identical CHECK_RATE
instructions (same patient, drug, and rate every time -- MEDSAFE-DSL has no
per-iteration variation). Since the check result cannot differ between
iterations, all N instructions are redundant after the first. This pass
collapses each such run into a single CHECK_RATE plus one LOOP_META
instruction recording the repeat count, and reports exactly how many
instructions were eliminated.
"""
from dataclasses import dataclass, field
from ir import Instruction


@dataclass
class OptimizationReport:
    original_count: int
    optimized_count: int
    eliminated: int
    notes: list = field(default_factory=list)


class Optimizer:
    def __init__(self, instrs: list[Instruction]):
        self.instrs = instrs

    def optimize(self) -> tuple[list[Instruction], OptimizationReport]:
        original_count = len(self.instrs)
        notes = []

        # Collect every repeat group's member instructions, in first-seen order.
        groups: dict[str, list[Instruction]] = {}
        for instr in self.instrs:
            grp = instr.operands.get("repeat_group")
            if instr.opcode == "CHECK_RATE" and grp is not None:
                groups.setdefault(grp, []).append(instr)

        for grp, members in groups.items():
            eliminated = len(members) - 1
            if eliminated > 0:
                notes.append(
                    f"Collapsed {len(members)} identical CHECK_RATE instructions for "
                    f"repeat group '{grp}' into 1 CHECK_RATE + 1 LOOP_META "
                    f"(loop-invariant code motion) -- eliminated {eliminated} "
                    f"redundant instruction(s)."
                )

        result: list[Instruction] = []
        addr = 0
        emitted_groups: set[str] = set()
        for instr in self.instrs:
            grp = instr.operands.get("repeat_group")
            if instr.opcode == "CHECK_RATE" and grp is not None:
                if grp in emitted_groups:
                    continue  # redundant repetition of an already-emitted check
                emitted_groups.add(grp)
                merged_ops = dict(instr.operands)
                merged_ops.pop("repeat_group", None)
                merged_ops["subject"] = grp
                result.append(Instruction(addr, "CHECK_RATE", merged_ops)); addr += 1
                result.append(Instruction(addr, "LOOP_META",
                                           {"group": grp, "repeat_count": len(groups[grp])}))
                addr += 1
            else:
                result.append(Instruction(addr, instr.opcode, instr.operands)); addr += 1

        optimized_count = len(result)
        report = OptimizationReport(original_count, optimized_count,
                                     original_count - optimized_count, notes)
        return result, report
