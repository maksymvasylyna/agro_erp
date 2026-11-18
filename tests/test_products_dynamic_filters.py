"""Product filter rendering: instant client search and no-JS fallback."""
import unittest

from app import create_app
from extensions import db
from modules.reference.products.models import Product


class ProductsDynamicFilterTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config["TESTING"] = True
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.session.add_all([
            Product(name="LIVE-FILTER ALPHA", composition="азоксистробін 100 г/л", is_archived=False),
            Product(name="LIVE-FILTER BETA", composition="тіаметоксам 250 г/кг", is_archived=False),
            Product(name="ARCHIVED-FILTER GAMMA", is_archived=True),
        ])
        db.session.commit()

    def tearDown(self):
        Product.query.filter(Product.name.in_(
            ("LIVE-FILTER ALPHA", "LIVE-FILTER BETA", "ARCHIVED-FILTER GAMMA")
        )).delete(synchronize_session=False)
        db.session.commit()
        self.ctx.pop()

    def test_instant_filters_have_all_rows_and_no_apply_button(self):
        with self.app.test_client() as client:
            result = client.get("/products?q=LIVE-FILTER ALPHA")
            self.assertEqual(200, result.status_code)
            html = result.get_data(as_text=True)
            self.assertIn("LIVE-FILTER ALPHA", html)
            self.assertIn("LIVE-FILTER BETA", html)
            self.assertNotIn("ARCHIVED-FILTER GAMMA", html)
            self.assertIn('id="products-filter-form"', html)
            self.assertIn('data-product-row', html)
            self.assertIn('data-search="LIVE-FILTER ALPHA азоксистробін 100 г/л"', html)
            self.assertIn('js/products_filters.js', html)
            self.assertIn('id="products-reset-filters"', html)
            self.assertIn('id="products-no-matches"', html)
            self.assertNotIn('type="submit" class="btn btn-primary"', html)
            self.assertIn("<noscript>", html)

    def test_server_filter_fallback(self):
        with self.app.test_client() as client:
            result = client.get("/products?q=LIVE-FILTER ALPHA&server_filter=1")
            self.assertEqual(200, result.status_code)
            html = result.get_data(as_text=True)
            self.assertIn("LIVE-FILTER ALPHA", html)
            self.assertNotIn("LIVE-FILTER BETA", html)

    def test_archive_scope_still_applied(self):
        with self.app.test_client() as client:
            response = client.get("/products?archived=archived")
            html = response.get_data(as_text=True)
            self.assertIn("ARCHIVED-FILTER GAMMA", html)
            self.assertNotIn("LIVE-FILTER ALPHA", html)


if __name__ == "__main__":
    unittest.main()
