import sys, os, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from symbol_table import SymbolTable, SymbolCollisionError


class TestSymbolTable(unittest.TestCase):

    def test_insert_and_lookup(self):
        st = SymbolTable()
        st.insert("p1", "patient", "Patient(weight: kg)", 70.0, 1, 1)
        entry = st.lookup("p1")
        self.assertEqual(entry.kind, "patient")

    def test_lookup_missing_returns_none(self):
        st = SymbolTable()
        self.assertIsNone(st.lookup("ghost"))

    def test_duplicate_declaration_raises_collision(self):
        st = SymbolTable()
        st.insert("p1", "patient", "Patient(weight: kg)", 70.0, 1, 1)
        with self.assertRaises(SymbolCollisionError):
            st.insert("p1", "patient", "Patient(weight: kg)", 65.0, 5, 1)

    def test_cross_kind_collision_raises(self):
        st = SymbolTable()
        st.insert("x", "patient", "Patient(weight: kg)", 70.0, 1, 1)
        with self.assertRaises(SymbolCollisionError):
            st.insert("x", "drug", "Drug(max_rate: mg/hr)", 10.0, 2, 1)

    def test_all_entries_returns_every_symbol(self):
        st = SymbolTable()
        st.insert("p1", "patient", "Patient(weight: kg)", 70.0, 1, 1)
        st.insert("d1", "drug", "Drug(max_rate: mg/hr)", 10.0, 2, 1)
        self.assertEqual(len(st.all_entries()), 2)


if __name__ == "__main__":
    unittest.main()
