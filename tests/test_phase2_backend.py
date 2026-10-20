import sys, os, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from lexer import Lexer
from parser import Parser
from semantic import SemanticAnalyzer
from ir import IRGenerator, Instruction
from optimizer import Optimizer
import bytecode

SIMPLE_SRC = """
PATIENT p1 { WEIGHT: 70 kg; }
DRUG dopamine { MAX_RATE: 20 mg/hr; }
INFUSION inf1 FOR p1 USING dopamine AT 15 mg/hr;
"""

REPEAT_SRC = """
PATIENT p1 { WEIGHT: 70 kg; }
DRUG dopamine { MAX_RATE: 20 mg/hr; }
REPEAT r1 FOR p1 USING dopamine AT 10 mg/hr EVERY 4 hr UNTIL 24 hr;
"""


def _compile_to_ir(src):
    program = Parser(Lexer(src).tokenize()).parse_program()
    analyzer = SemanticAnalyzer(program)
    symtab = analyzer.analyze()
    return IRGenerator(program, symtab, analyzer.checks).generate()


class TestIRGeneration(unittest.TestCase):
    def test_emits_def_patient_and_def_drug(self):
        instrs = _compile_to_ir(SIMPLE_SRC)
        opcodes = [i.opcode for i in instrs]
        self.assertIn("DEF_PATIENT", opcodes)
        self.assertIn("DEF_DRUG", opcodes)

    def test_emits_check_rate_for_infusion(self):
        instrs = _compile_to_ir(SIMPLE_SRC)
        check_instrs = [i for i in instrs if i.opcode == "CHECK_RATE"]
        self.assertEqual(len(check_instrs), 1)
        self.assertEqual(check_instrs[0].operands["verdict"], "SAFE")

    def test_ends_with_halt(self):
        instrs = _compile_to_ir(SIMPLE_SRC)
        self.assertEqual(instrs[-1].opcode, "HALT")

    def test_repeat_unrolls_into_n_check_rate_instructions(self):
        instrs = _compile_to_ir(REPEAT_SRC)
        check_instrs = [i for i in instrs if i.opcode == "CHECK_RATE"]
        self.assertEqual(len(check_instrs), 6)  # 24hr / 4hr
        self.assertTrue(all(i.operands.get("repeat_group") == "r1" for i in check_instrs))


class TestOptimizer(unittest.TestCase):
    def test_collapses_repeated_checks(self):
        instrs = _compile_to_ir(REPEAT_SRC)
        optimized, report = Optimizer(instrs).optimize()
        opt_checks = [i for i in optimized if i.opcode == "CHECK_RATE"]
        opt_loop_meta = [i for i in optimized if i.opcode == "LOOP_META"]
        self.assertEqual(len(opt_checks), 1)
        self.assertEqual(len(opt_loop_meta), 1)
        self.assertEqual(opt_loop_meta[0].operands["repeat_count"], 6)

    def test_reports_correct_elimination_count(self):
        instrs = _compile_to_ir(REPEAT_SRC)
        _optimized, report = Optimizer(instrs).optimize()
        # 6 CHECK_RATE -> 1 CHECK_RATE + 1 LOOP_META: net change is -4 instructions.
        self.assertEqual(report.original_count - report.optimized_count, 4)
        self.assertTrue(len(report.notes) >= 1)

    def test_no_op_on_program_without_repeats(self):
        instrs = _compile_to_ir(SIMPLE_SRC)
        optimized, report = Optimizer(instrs).optimize()
        self.assertEqual(report.original_count, report.optimized_count)
        self.assertEqual(report.eliminated, 0)


class TestBytecode(unittest.TestCase):
    def test_assemble_disassemble_roundtrip_opcodes(self):
        instrs = _compile_to_ir(SIMPLE_SRC)
        optimized, _report = Optimizer(instrs).optimize()
        data = bytecode.assemble(optimized)
        restored = bytecode.disassemble(data)
        self.assertEqual([i.opcode for i in optimized], [i.opcode for i in restored])

    def test_assemble_disassemble_roundtrip_operands(self):
        instrs = _compile_to_ir(SIMPLE_SRC)
        optimized, _report = Optimizer(instrs).optimize()
        data = bytecode.assemble(optimized)
        restored = bytecode.disassemble(data)
        for original, back in zip(optimized, restored):
            # Values round-trip as strings (the binary format is string-keyed);
            # compare against the stringified original.
            expected = {k: str(v) for k, v in original.operands.items()}
            self.assertEqual(back.operands, expected)

    def test_bad_magic_raises(self):
        with self.assertRaises(bytecode.BytecodeError):
            bytecode.disassemble(b"NOPE-not-a-bytecode-file")

    def test_bytecode_starts_with_magic(self):
        instrs = _compile_to_ir(SIMPLE_SRC)
        data = bytecode.assemble(instrs)
        self.assertEqual(data[:4], bytecode.MAGIC)


if __name__ == "__main__":
    unittest.main()
