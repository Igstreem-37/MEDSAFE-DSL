"""
bytecode.py
Phase 2 bytecode generator for MEDSAFE-DSL.

Encodes an optimized IR instruction list into a compact binary format:

    [MAGIC 4B]["MDSC"] [VERSION 1B] [INSTR_COUNT 2B]
    for each instruction:
        [OPCODE_ID 1B] [OPERAND_COUNT 2B]
        for each operand:
            [KEY_LEN 1B][KEY bytes] [VAL_LEN 2B][VAL bytes]

All integers are big-endian (struct format '>'). This is a real, lossless
binary encoding -- assemble() and disassemble() round-trip exactly -- not a
text mock-up. Phase 3 executes this bytecode on the MEDSAFE VM (vm.py).
"""
import struct
from ir import Instruction

OPCODES = ["DEF_PATIENT", "DEF_DRUG", "CHECK_RATE", "WEIGHT_CMP", "LOOP_META", "HALT",
           # Phase 3 additions (appended so Phase 2 opcode ids are unchanged)
           "DEF_INTERACT", "INFUSE", "SCHEDULE", "CHECK_TOTAL", "CHECK_INTERACT"]
OPCODE_ID = {name: i for i, name in enumerate(OPCODES)}
ID_OPCODE = {i: name for name, i in OPCODE_ID.items()}

MAGIC = b"MDSC"   # MedSafe-DSl bytecode
VERSION = 1


class BytecodeError(Exception):
    pass


def assemble(instrs: list[Instruction]) -> bytes:
    buf = bytearray()
    buf += MAGIC
    buf += struct.pack(">B", VERSION)
    buf += struct.pack(">H", len(instrs))
    for instr in instrs:
        if instr.opcode not in OPCODE_ID:
            raise BytecodeError(f"unknown opcode {instr.opcode!r}")
        buf += struct.pack(">B", OPCODE_ID[instr.opcode])
        items = list(instr.operands.items())
        buf += struct.pack(">H", len(items))
        for k, v in items:
            k_bytes = k.encode("utf-8")
            v_bytes = str(v).encode("utf-8")
            buf += struct.pack(">B", len(k_bytes)) + k_bytes
            buf += struct.pack(">H", len(v_bytes)) + v_bytes
    return bytes(buf)


def disassemble(data: bytes) -> list[Instruction]:
    """Decode a bytecode buffer. Any malformed, truncated or corrupted input
    is reported as BytecodeError (never as a raw struct/index/unicode error)."""
    try:
        return _disassemble(data)
    except (struct.error, IndexError) as exc:
        raise BytecodeError("corrupted or truncated bytecode (data ended unexpectedly)") from exc
    except KeyError as exc:
        raise BytecodeError(f"corrupted bytecode (unknown opcode id {exc})") from exc
    except UnicodeDecodeError as exc:
        raise BytecodeError("corrupted bytecode (operand is not valid UTF-8 text)") from exc


def _disassemble(data: bytes) -> list[Instruction]:
    if data[:4] != MAGIC:
        raise BytecodeError("bad magic number: not a MEDSAFE-DSL bytecode file")
    offset = 4
    _version, = struct.unpack_from(">B", data, offset); offset += 1
    count, = struct.unpack_from(">H", data, offset); offset += 2

    instrs = []
    for addr in range(count):
        opcode_id, = struct.unpack_from(">B", data, offset); offset += 1
        opcode = ID_OPCODE[opcode_id]
        n_items, = struct.unpack_from(">H", data, offset); offset += 2
        operands = {}
        for _ in range(n_items):
            klen, = struct.unpack_from(">B", data, offset); offset += 1
            k = data[offset:offset + klen].decode("utf-8"); offset += klen
            vlen, = struct.unpack_from(">H", data, offset); offset += 2
            v = data[offset:offset + vlen].decode("utf-8"); offset += vlen
            operands[k] = v
        instrs.append(Instruction(addr, opcode, operands))
    return instrs
