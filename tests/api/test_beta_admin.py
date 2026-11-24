from contextlib import closing

import httpx
from fastapi.testclient import TestClient

from app.beta.access import BetaAccess
from app.beta.admin_access import ADMIN_COOKIE, AdminAccess
from app.core.config import Settings
from app.questions.catalog import load_cards
from app.server import create_app

ORIGIN = "https://mockroom.dynv6.net"
HEADERS = {"Origin": ORIGIN, "X-Mockroom-Client": "web"}
CREDENTIALS = {"login": "admin", "password": "long test-only admin password"}


def test_admin_quota_changes_are_private_and_preserve_usage(tmp_path, monkeypatch):
    monkeypatch.setattr("app.storage.store.load_cards", lambda: load_cards()[:1])
    settings = Settings(data_dir=tmp_path, beta_origin=ORIGIN, openrouter_key="test-only",
                        model="test-model", embedding_model="", qdrant_url="", llm_base_url="")
    app = create_app(settings)
    access = BetaAccess(tmp_path / "beta.sqlite3")
    admin = AdminAccess(access.connect)
    admin.set_credentials(**CREDENTIALS)
    owner, _, code = access.issue("Tester", 60)
    access.quotas.consume_provider(owner, 30, 100)

    def budget_fetch(url, **kwargs):
        assert url == "https://openrouter.ai/api/v1/key"
        assert kwargs["headers"] == {"Authorization": "Bearer test-only"}
        return httpx.Response(200, request=httpx.Request("GET", url), json={
            "data": {"limit": 2, "limit_remaining": 1.7, "limit_reset": None, "usage_daily": 0.1,
                     "key": "never-return-this"},
        })

    monkeypatch.setattr("app.integrations.openrouter.httpx.get", budget_fetch)
    with TestClient(app, base_url=ORIGIN) as operator, closing(TestClient(app, base_url=ORIGIN)) as tester:
        page = operator.get("/admin")
        assert page.status_code == 200 and "frame-ancestors 'none'" in page.headers["content-security-policy"]
        assert tester.post("/api/beta/redeem", headers=HEADERS, json={"code": code}).status_code == 200
        assert tester.put("/api/beta/profile", headers=HEADERS, json={"name": "Алексей"}).status_code == 200
        for endpoint in ("usage", "openrouter"):
            assert tester.get("/api/admin/" + endpoint).status_code == 401
        change = {"target": "account", "account_id": owner, "maximum": 0}
        assert tester.put("/api/admin/limits", headers=HEADERS, json=change).status_code == 401
        assert operator.post("/api/admin/login", json=CREDENTIALS).status_code == 403
        denied = operator.post("/api/admin/login", headers=HEADERS, json=CREDENTIALS | {"password": "wrong"})
        assert denied.status_code == 401
        invalid = operator.post("/api/admin/login", headers=HEADERS, json={"password": "sensitive test data"})
        assert invalid.status_code == 422 and "sensitive test data" not in invalid.text
        logged_in = operator.post("/api/admin/login", headers=HEADERS, json=CREDENTIALS)
        assert logged_in.status_code == 200
        assert all(part in logged_in.headers["set-cookie"].lower() for part in ("secure", "httponly", "samesite=strict"))
        assert operator.get("/api/history").status_code == 401
        assert operator.put("/api/admin/limits", headers=HEADERS | {"Origin": "https://elsewhere.test"},
                            json=change).status_code == 403
        usage = operator.put("/api/admin/limits", headers=HEADERS, json=change).json()
        assert usage["global"] == {"used": 1, "limit": 100, "remaining": 99}
        assert usage["accounts"][0]["label"] == "Tester" and usage["accounts"][0]["display_name"] == "Алексей"
        assert usage["accounts"][0]["used"] == 1 and usage["accounts"][0]["remaining"] == 0
        assert usage["build"]["version"] == operator.get("/api/health").json()["version"]
        usage = operator.put("/api/admin/limits", headers=HEADERS, json=change | {"maximum": None}).json()
        assert usage["accounts"][0]["remaining"] == 29
        usage = operator.put("/api/admin/limits", headers=HEADERS, json={
            "target": "global", "maximum": 5,
        }).json()
        assert usage["accounts"][0]["remaining"] == 4
        assert operator.get("/api/admin/openrouter").json() == {
            "available": True, "limit": 2, "limit_remaining": 1.7, "limit_reset": None, "usage_daily": 0.1,
        }
        token = operator.cookies.get(ADMIN_COOKIE)
        assert operator.post("/api/admin/logout", headers=HEADERS).status_code == 200
        assert not admin.authenticate(token)
        assert operator.get("/api/admin/usage").status_code == 401
