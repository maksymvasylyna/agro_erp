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


    def test_directory_shows_informational_data_only(self):
        app = create_app()
        app.config["TESTING"] = True
        with app.app_context():
            product = Product(
                name="TEST HIDDEN DETAILS",
                formulation_code="SC",
                composition="азоксистробін 100 г/л",
                registration_status="Потребує звірки з Держреєстром",
                registration_number="INTERNAL-REG-TEST",
                source_note="INTERNAL-SOURCE-TEST",
            )
            db.session.add(product)
            db.session.commit()
            product_id = product.id

            with app.test_client() as client:
                index = client.get("/products")
                self.assertEqual(200, index.status_code)
                html = index.get_data(as_text=True)
                self.assertIn("TEST HIDDEN DETAILS", html)
                self.assertIn("азоксистробін 100 г/л", html)
                self.assertNotIn("Залежні записи", html)
                self.assertNotIn("Реєстрація", html)
                self.assertNotIn("INTERNAL-REG-TEST", html)
                self.assertNotIn("INTERNAL-SOURCE-TEST", html)
                edit = client.get(f"/products/{product_id}/edit")
                self.assertEqual(200, edit.status_code)
                edit_html = edit.get_data(as_text=True)
                self.assertNotIn("Статус державної реєстрації", edit_html)
                self.assertNotIn("INTERNAL-REG-TEST", edit_html)
                self.assertIn("Препаративна форма", edit_html)

            saved = db.session.get(Product, product_id)
            self.assertEqual("INTERNAL-REG-TEST", saved.registration_number)
            self.assertEqual("INTERNAL-SOURCE-TEST", saved.source_note)
            db.session.delete(saved)
            db.session.commit()


if __name__ == "__main__":
    unittest.main()
