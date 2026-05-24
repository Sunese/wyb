import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../src"))

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from categorize.main import app, Base, get_db


@pytest.fixture
def client():
    """TestClient backed by an isolated in-memory SQLite database.

    StaticPool is required so that create_all and the session used by each
    request share the same underlying connection — without it every new
    connection to sqlite:///:memory: gets a separate empty database.

    Does NOT use TestClient as a context manager, so the lifespan (which
    would try to connect to RabbitMQ) is never triggered.
    """
    test_engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
    Base.metadata.create_all(test_engine)

    def override_get_db():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()
    Base.metadata.drop_all(test_engine)


# ── Rules ─────────────────────────────────────────────────────────────────────

class TestRulesApi:
    def test_get_rules_empty(self, client):
        res = client.get("/rules")
        assert res.status_code == 200
        assert res.json() == []

    def test_post_rule_returns_201_with_fields(self, client):
        payload = {"name": "Groceries", "pattern": "MENY", "matchType": "Contains",
                   "category": "Groceries", "priority": 10}
        res = client.post("/rules", json=payload)
        assert res.status_code == 201
        body = res.json()
        assert body["name"] == "Groceries"
        assert body["pattern"] == "MENY"
        assert body["matchType"] == "Contains"
        assert body["category"] == "Groceries"
        assert body["priority"] == 10
        assert "id" in body
        assert "createdAt" in body

    def test_post_rule_appears_in_get(self, client):
        client.post("/rules", json={"name": "Subs", "pattern": "NETFLIX",
                                    "matchType": "Contains", "category": "Subscriptions", "priority": 5})
        rules = client.get("/rules").json()
        assert any(r["pattern"] == "NETFLIX" for r in rules)

    def test_get_rules_ordered_by_priority(self, client):
        client.post("/rules", json={"name": "A", "pattern": "AAA", "matchType": "Contains",
                                    "category": "Groceries", "priority": 20})
        client.post("/rules", json={"name": "B", "pattern": "BBB", "matchType": "Contains",
                                    "category": "Groceries", "priority": 1})
        client.post("/rules", json={"name": "C", "pattern": "CCC", "matchType": "Contains",
                                    "category": "Groceries", "priority": 10})
        rules = client.get("/rules").json()
        priorities = [r["priority"] for r in rules]
        assert priorities == sorted(priorities)

    def test_delete_rule_returns_204(self, client):
        rule_id = client.post("/rules", json={"name": "Del", "pattern": "DEL",
                                              "matchType": "Exact", "category": "Uncategorized",
                                              "priority": 99}).json()["id"]
        res = client.delete(f"/rules/{rule_id}")
        assert res.status_code == 204

    def test_delete_rule_removes_it_from_get(self, client):
        rule_id = client.post("/rules", json={"name": "Gone", "pattern": "GONE",
                                              "matchType": "Exact", "category": "Uncategorized",
                                              "priority": 50}).json()["id"]
        client.delete(f"/rules/{rule_id}")
        rules = client.get("/rules").json()
        assert not any(r["id"] == rule_id for r in rules)

    def test_delete_rule_not_found(self, client):
        import uuid
        res = client.delete(f"/rules/{uuid.uuid4()}")
        assert res.status_code == 404


# ── Merchants ─────────────────────────────────────────────────────────────────

class TestMerchantsApi:
    def test_get_merchants_empty(self, client):
        res = client.get("/merchants")
        assert res.status_code == 200
        assert res.json() == []

    def test_post_merchant_without_default_category(self, client):
        res = client.post("/merchants", json={"canonicalName": "MENY"})
        assert res.status_code == 201
        body = res.json()
        assert body["canonicalName"] == "MENY"
        assert body["defaultCategory"] is None
        assert body["aliases"] == []
        assert "id" in body

    def test_post_merchant_with_default_category(self, client):
        res = client.post("/merchants", json={"canonicalName": "MobilePay",
                                              "defaultCategory": "Transfer"})
        assert res.status_code == 201
        body = res.json()
        assert body["canonicalName"] == "MobilePay"
        assert body["defaultCategory"] == "Transfer"

    def test_post_merchant_appears_in_get(self, client):
        client.post("/merchants", json={"canonicalName": "NETTO"})
        merchants = client.get("/merchants").json()
        assert any(m["canonicalName"] == "NETTO" for m in merchants)

    def test_delete_merchant_returns_204(self, client):
        merchant_id = client.post("/merchants", json={"canonicalName": "ALDI"}).json()["id"]
        res = client.delete(f"/merchants/{merchant_id}")
        assert res.status_code == 204

    def test_delete_merchant_removes_it(self, client):
        merchant_id = client.post("/merchants", json={"canonicalName": "REMA"}).json()["id"]
        client.delete(f"/merchants/{merchant_id}")
        merchants = client.get("/merchants").json()
        assert not any(m["id"] == merchant_id for m in merchants)

    def test_delete_merchant_not_found(self, client):
        import uuid
        assert client.delete(f"/merchants/{uuid.uuid4()}").status_code == 404

    def test_post_alias_appears_in_get_merchants(self, client):
        merchant_id = client.post("/merchants", json={"canonicalName": "FAKCO"}).json()["id"]
        res = client.post(f"/merchants/{merchant_id}/aliases",
                          json={"pattern": "FAKCO", "matchType": "StartsWith"})
        assert res.status_code == 201
        body = res.json()
        assert body["pattern"] == "FAKCO"
        assert body["matchType"] == "StartsWith"
        assert body["merchantId"] == merchant_id

        merchants = client.get("/merchants").json()
        merchant = next(m for m in merchants if m["id"] == merchant_id)
        assert len(merchant["aliases"]) == 1
        assert merchant["aliases"][0]["pattern"] == "FAKCO"

    def test_post_alias_not_found_for_unknown_merchant(self, client):
        import uuid
        res = client.post(f"/merchants/{uuid.uuid4()}/aliases",
                          json={"pattern": "X", "matchType": "Contains"})
        assert res.status_code == 404

    def test_delete_alias_removes_it_merchant_remains(self, client):
        merchant_id = client.post("/merchants", json={"canonicalName": "ALDI2"}).json()["id"]
        alias_id = client.post(f"/merchants/{merchant_id}/aliases",
                               json={"pattern": "ALDI", "matchType": "Contains"}).json()["id"]
        assert client.delete(f"/aliases/{alias_id}").status_code == 204

        merchants = client.get("/merchants").json()
        merchant = next(m for m in merchants if m["id"] == merchant_id)
        assert merchant["aliases"] == []

    def test_delete_alias_not_found(self, client):
        import uuid
        assert client.delete(f"/aliases/{uuid.uuid4()}").status_code == 404

    def test_delete_merchant_cascades_aliases(self, client):
        merchant_id = client.post("/merchants", json={"canonicalName": "CASCADE"}).json()["id"]
        alias_id = client.post(f"/merchants/{merchant_id}/aliases",
                               json={"pattern": "CASCADE", "matchType": "Exact"}).json()["id"]
        client.delete(f"/merchants/{merchant_id}")

        # Alias is gone too
        assert client.delete(f"/aliases/{alias_id}").status_code == 404
