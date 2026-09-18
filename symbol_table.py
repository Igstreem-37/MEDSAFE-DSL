"""
symbol_table.py
Flat, namespaced symbol table for MEDSAFE-DSL. Two independent namespaces
(patients, drugs) are maintained so that a patient and a drug may not share
an identifier, and re-declaration within the same namespace is rejected as
a collision.
"""
from dataclasses import dataclass, field


class SymbolCollisionError(Exception):
    def __init__(self, message: str, line: int, col: int):
        super().__init__(f"[Symbol Error] {message} at line {line}, column {col}")
        self.line = line
        self.col = col


@dataclass
class SymbolEntry:
    name: str
    kind: str            # "patient" | "drug"
    inferred_type: str    # e.g. "Patient(weight: kg)" or "Drug(max_rate: mg/hr)"
    baseline_value: float
    declared_at: tuple[int, int]


@dataclass
class SymbolTable:
    _entries: dict[str, SymbolEntry] = field(default_factory=dict)

    def insert(self, name: str, kind: str, inferred_type: str,
               baseline_value: float, line: int, col: int) -> None:
        if name in self._entries:
            existing = self._entries[name]
            raise SymbolCollisionError(
                f"identifier {name!r} already declared as {existing.kind} "
                f"at line {existing.declared_at[0]}, column {existing.declared_at[1]}",
                line, col,
            )
        self._entries[name] = SymbolEntry(name, kind, inferred_type, baseline_value, (line, col))

    def lookup(self, name: str) -> SymbolEntry | None:
        return self._entries.get(name)

    def all_entries(self) -> list[SymbolEntry]:
        return list(self._entries.values())
