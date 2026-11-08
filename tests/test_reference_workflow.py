"""Integration regression tests for shared reference data, using only SQLite."""
import os
import unittest

os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ.pop("RENDER_DATABASE_URL", None)
os.environ["SECRET_KEY"] = "disposable-reference-tests-secret"

from app import create_app  # noqa: E402
from extensions import db  # noqa: E402
from modules.reference.categories.models import Category  # noqa: E402
from modules.reference.groups.models import Group  # noqa: E402
from modules.reference.units.models import Unit  # noqa: E402
from modules.reference.manufacturers.models import Manufacturer  # noqa: E402
from modules.reference.payers.models import Payer  # noqa: E402
from modules.reference.currencies.models import Currency  # noqa: E402
from modules.reference.products.models import Product  # noqa: E402
from modules.reference.clusters.models import Cluster  # noqa: E402
from modules.reference.companies.models import Company  # noqa: E402
from modules.reference.warehouses.models import Warehouse  # noqa: E402


class ReferenceDirectoryWorkflowTest(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.create_all()
        self.client = self.app.test_client()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def test_all_reference_lists_and_forms_share_templates(self):
        paths = (
            "/categories/", "/groups/", "/manufacturers/", "/payers/",
            "/units", "/reference/treatment_types/", "/currencies/",
            "/products", "/reference/warehouses/",
        )
        for path in paths:
            with self.subTest(path=path):
                res = self.client.get(path)
                self.assertEqual(res.status_code, 200)
                html = res.get_data(as_text=True)
                self.assertIn("До головного меню", html)
                self.assertIn("erp-reference-page", html)
        self.assertEqual(self.client.get("/reference").status_code, 200)
        for path in (
            "/categories/create", "/groups/create", "/manufacturers/create",
            "/payers/create", "/units/create", "/reference/treatment_types/create",
            "/currencies/create", "/products/create",
            "/reference/warehouses/new",
        ):
            with self.subTest(path=path):
                res = self.client.get(path)
                self.assertEqual(res.status_code, 200)
                self.assertIn('erp-form-card', res.get_data(as_text=True))

    def test_basic_reference_deduplication_and_currency_codes(self):
        create = self.client.post("/categories/create", data={"name": " Гербіциди  "})
        self.assertEqual(create.status_code, 302)
        self.assertEqual(Category.query.count(), 1)
        duplicate = self.client.post("/categories/create", data={"name": "гербіциди"})
        self.assertEqual(duplicate.status_code, 200)
        self.assertEqual(Category.query.count(), 1)

        self.assertEqual(self.client.post("/currencies/create", data={
            "code": " usd ", "name": " Долар США ",
        }).status_code, 302)
        self.assertEqual(Currency.query.one().code, "USD")
        self.assertEqual(self.client.post("/currencies/create", data={
            "code": "USD", "name": "Долар",
        }).status_code, 200)
        self.assertEqual(Currency.query.count(), 1)

    def test_product_uses_directory_values_and_protects_related_data(self):
        category = Category(name="ЗЗР")
        group = Group(name="Захист рослин")
        unit = Unit(name="л")
        manufacturer = Manufacturer(name="Виробник А")
        db.session.add_all([category, group, unit, manufacturer])
        db.session.commit()

        payload = {
            "name": " Препарат   А ",
            "category": str(category.id),
            "group": str(group.id),
            "unit": str(unit.id),
            "manufacturer": str(manufacturer.id),
            "container": "5",
        }
        self.assertEqual(self.client.post("/products/create", data=payload).status_code, 302)
        prod = Product.query.one()
        self.assertEqual(prod.name, "Препарат А")
        self.assertEqual(prod.category_id, category.id)
        self.assertEqual(prod.manufacturer_id, manufacturer.id)
        self.assertEqual(self.client.post("/products/create", data=payload).status_code, 200)
        self.assertEqual(Product.query.count(), 1)

        self.assertEqual(self.client.post(
            f"/categories/delete/{category.id}"
        ).status_code, 302)
        self.assertIsNotNone(db.session.get(Category, category.id))
        self.assertEqual(self.client.get("/products").status_code, 200)

    def test_warehouse_company_link_and_soft_deactivation(self):
        cluster = Cluster(name="Кластер тест")
        db.session.add(cluster)
        db.session.flush()
        company = Company(name="Підприємство тест", cluster_id=cluster.id)
        db.session.add(company)
        db.session.commit()
        new = self.client.post("/reference/warehouses/new", data={
            "company": str(company.id), "name": " Склад №1 ",
            "address": "Село", "is_active": "y",
        })
        self.assertEqual(new.status_code, 302)
        warehouse = Warehouse.query.one()
        self.assertEqual(warehouse.company_id, company.id)
        result = self.client.get("/reference/warehouses/api/by_company",
                                 query_string={"company_id": company.id})
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json[0]["name"], "Склад №1")
        self.assertEqual(
            self.client.post(f"/reference/warehouses/{warehouse.id}/delete").status_code, 302
        )
        db.session.refresh(warehouse)
        self.assertFalse(warehouse.is_active)
        self.assertEqual(self.client.get(
            "/reference/warehouses/api/by_company",
            query_string={"company_id": company.id}
        ).json, [])


if __name__ == "__main__":
    unittest.main()
