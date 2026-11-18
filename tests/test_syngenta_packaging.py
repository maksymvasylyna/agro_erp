"""Syngenta packaging mapping & safeguards. No connection to production."""
import json
import unittest
from pathlib import Path

from scripts.backfill_syngenta_packaging_2026 import validate_payload


ROOT = Path(__file__).parents[1] / "modules/reference/products"


class PackagingCatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = json.loads((ROOT / "syngenta_catalog_2026.json").read_text(encoding="utf-8"))
        cls.pack = json.loads((ROOT / "syngenta_packaging_2026.json").read_text(encoding="utf-8"))

    def current_rows(self):
        return [
            {"id": 53 + i, "name": x["name"], "is_archived": False, "container": None}
            for i, x in enumerate(self.source["products"])
        ]

    def test_all_108_have_largest_package(self):
        validate_payload(self.pack, self.source, self.current_rows())
        self.assertEqual(108, len(self.pack["entries"]))
        selected = {entry["name"]: entry["container"] for entry in self.pack["entries"]}
        self.assertEqual("1000 л", selected["CRUISER 350 FS"])
        self.assertEqual("1000 л", selected["MAXIM XL 035 FS"])
        self.assertEqual("20 л", selected["VIBRANCE INTEGRAL 235 FS"])
        self.assertEqual("100 л", selected["PRIMEXTRA TZ GOLD 500 SC"])
        self.assertEqual("20 кг", selected["THIOVIT JET 80 WG"])
        self.assertEqual("5 л", selected["AMPLIGO 150 ZC"])

    def test_reject_changed_product_identity(self):
        rows = self.current_rows()
        rows[3]["name"] = "Another preparation"
        with self.assertRaises(ValueError):
            validate_payload(self.pack, self.source, rows)

    def test_reject_nonempty_existing_packaging(self):
        rows = self.current_rows()
        rows[17]["container"] = "50 л"
        with self.assertRaises(ValueError):
            validate_payload(self.pack, self.source, rows)

    def test_reject_new_product(self):
        rows = self.current_rows()
        rows.append({"id": 161, "name": "NEW", "is_archived": False, "container": None})
        with self.assertRaises(ValueError):
            validate_payload(self.pack, self.source, rows)

    def test_reject_incorrect_source_mapping(self):
        invalid = {**self.pack, "entries": [dict(x) for x in self.pack["entries"]]}
        invalid["entries"][0]["container"] = "20 ml"
        with self.assertRaises(ValueError):
            validate_payload(invalid, self.source, self.current_rows())


if __name__ == "__main__":
    unittest.main()
