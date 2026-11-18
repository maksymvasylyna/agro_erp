"""Pilot catalog checks run on disposable SQLite; never touch production DB."""
import json
import unittest
from pathlib import Path

from app import create_app
from extensions import db
from modules.reference.products.catalog_import import CATEGORY, sync_components
from modules.reference.products.models import Product, ActiveIngredient, ProductIngredient


class SyngentaCatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = Path(__file__).parents[1] / "modules/reference/products/syngenta_catalog_2026.json"

    def test_catalog_is_complete_unique_and_unverified(self):
        payload = json.loads(self.source.read_text(encoding="utf-8"))
        rows = payload["products"]
        self.assertEqual(108, len(rows))
        self.assertEqual(108, len({row["name"].casefold() for row in rows}))
        self.assertFalse(payload["registration_verified"])
        for row in rows:
            self.assertIn(row["type"], CATEGORY)
            self.assertTrue(row["name"] and row["formulation_code"] and row["composition"])
            self.assertEqual("Потребує звірки з Держреєстром", row["registration_status"])

    def test_normalized_product_ingredients(self):
        app = create_app()
        app.config["TESTING"] = True
        with app.app_context():
            product = Product(name="TEST COMPOSITION", is_archived=False)
            db.session.add(product)
            db.session.flush()
            sync_components(
                product,
                "азоксистробін 125 г/л; дифеноконазол 125 г/л; "
                "антидот клоквінтосет-мексил",
            )
            db.session.commit()
            components = ProductIngredient.query.filter_by(product_id=product.id).all()
            self.assertEqual(3, len(components))
            self.assertEqual(125.0, components[0].concentration_value)
            self.assertEqual("г/л", components[0].concentration_unit)
            self.assertTrue(components[2].is_safener)
            self.assertEqual(3, ActiveIngredient.query.count())
            db.session.delete(product)
            db.session.commit()


if __name__ == "__main__":
    unittest.main()
