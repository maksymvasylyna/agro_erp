"""Cap-20 Syngenta packaging update checks; no production access."""
import json
import unittest
from pathlib import Path

from scripts.cap_syngenta_packaging_20_2026 import validate_corrections, _size


ROOT = Path(__file__).parents[1] / "modules/reference/products"


class PackagingCap20Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.change = json.loads(
            (ROOT / "syngenta_packaging_cap20_2026.json").read_text(encoding="utf-8")
        )
        cls.original = json.loads(
            (ROOT / "syngenta_packaging_2026.json").read_text(encoding="utf-8")
        )

    def baseline(self):
        return [
            {"id": e["index"] + 52, "name": e["name"],
             "container": e["container"], "is_archived": False}
            for e in self.original["entries"]
        ]

    def test_eight_verified_corrections(self):
        validate_corrections(self.change, self.original, self.baseline())
        self.assertEqual(8, len(self.change["entries"]))
        for e in self.change["entries"]:
            value, unit = _size(e["next"])
            self.assertLessEqual(value, 20)
            self.assertIn(unit, ("л", "кг"))
        self.assertEqual(20, _size("20 л")[0])
        self.assertEqual(2.5, _size("2,5 кг")[0])

    def test_cannot_change_unexpected_new_packaging(self):
        rows = self.baseline()
        rows[56 - 1]["container"] = "20 л"
        with self.assertRaises(ValueError):
            validate_corrections(self.change, self.original, rows)

    def test_cannot_touch_extra_new_product(self):
        rows = self.baseline()
        rows.append({"id": 161, "name": "New", "container": "5 л", "is_archived": False})
        with self.assertRaises(ValueError):
            validate_corrections(self.change, self.original, rows)

    def test_all_other_products_unchanged(self):
        rows = self.baseline()
        rows[4]["container"] = "1 л"
        with self.assertRaises(ValueError):
            validate_corrections(self.change, self.original, rows)

    def test_cannot_select_nonexistent_20l(self):
        change = {**self.change, "entries": [dict(e) for e in self.change["entries"]]}
        change["entries"][1] = {**change["entries"][1], "next": "20 л"}
        with self.assertRaises(ValueError):
            validate_corrections(change, self.original, self.baseline())


if __name__ == "__main__":
    unittest.main()
