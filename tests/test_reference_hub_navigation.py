"""Reference menu consistency and directory route checks (isolated SQLite)."""
import unittest

from app import create_app


class ReferenceHubNavigationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.app.config["TESTING"] = True

    def test_reference_hub_matches_structure_navigation_and_style(self):
        with self.app.test_client() as client:
            reference = client.get("/reference")
            structure = client.get("/structure")
            self.assertEqual(reference.status_code, 200)
            self.assertEqual(structure.status_code, 200)
            html = reference.get_data(as_text=True)
            structure_html = structure.get_data(as_text=True)

            navigation = ('class="erp-page-nav d-flex justify-content-start mb-4" '
                          'aria-label="Навігація сторінки"')
            button = ('class="btn btn-outline-secondary erp-nav-button"'
                      '>← До головного меню</a>')
            self.assertIn(navigation, html)
            self.assertIn(button, html)
            self.assertIn(navigation, structure_html)
            self.assertIn(button, structure_html)
            self.assertNotIn('🏠 На головну', html)
            self.assertNotIn('border-success', html)
            self.assertEqual(html.count('class="container mt-4"'), 1)
            self.assertEqual(html.count('class="card h-100 border-0 tile-card position-relative"'), 13)
            self.assertEqual(html.count('class="stretched-link"'), 13)

    def test_all_existing_reference_links_are_kept(self):
        with self.app.test_request_context():
            # Calculate exact paths from blueprint routes instead of assuming
            # slash/underscore conventions differ across modules.
            from flask import url_for
            endpoints = [
                "units.index", "categories.index", "currencies.index",
                "products.index", "manufacturers.index", "payers.index",
                "cultures.index", "groups.index", "clusters.index",
                "companies.index", "warehouses.index", "fields.index",
                "treatment_types.index",
            ]
            links = [url_for(endpoint) for endpoint in endpoints]
            self.assertEqual(len(links), len(set(links)))
        with self.app.test_client() as client:
            html = client.get("/reference").get_data(as_text=True)
            for link in links:
                self.assertIn(f'href="{link}"', html)
            self.assertEqual(html.count('aria-label="Відкрити довідник'), 13)


if __name__ == "__main__":
    unittest.main()
