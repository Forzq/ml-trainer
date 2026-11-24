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


def test_admin_invites_notes_and_personal_quota_reset(tmp_path, monkeypatch):
    monkeypatch.setattr("app.storage.store.load_cards", lambda: load_cards()[:1])
    settings = Settings(data_dir=tmp_path, beta_origin=ORIGIN, beta_identity_daily_limit=30,
                        beta_total_daily_limit=10, embedding_model="", qdrant_url="")
    app = create_app(settings)
    access = BetaAccess(tmp_path / "beta.sqlite3")
    AdminAccess(access.connect).set_credentials(**CREDENTIALS)
    account, _, original = access.issue("Current", 60)
    access.quotas.consume_provider(account, 30, 10)
    notes = f"/api/admin/accounts/{account}/notes"
    reset = f"/api/admin/accounts/{account}/reset-usage"
    invites = "/api/admin/invites"

    with (TestClient(app, base_url=ORIGIN) as operator,
          closing(TestClient(app, base_url=ORIGIN)) as current,
          closing(TestClient(app, base_url=ORIGIN)) as invited):
        assert current.post("/api/beta/redeem", headers=HEADERS, json={"code": original}).status_code == 200
        assert current.get("/api/beta/quota").json()["remaining"] == 9
        assert current.post(notes, headers=HEADERS, json={"text": "private"}).status_code == 401
        assert current.post(reset, headers=HEADERS).status_code == 401
        assert current.post(invites, headers=HEADERS, json={"label": "New"}).status_code == 401
        assert operator.post("/api/admin/login", headers=HEADERS, json=CREDENTIALS).status_code == 200
        assert operator.post(notes, headers=HEADERS, json={"text": "  "}).status_code == 422
        assert operator.post(notes, headers=HEADERS, json={"text": "<b>Личная заметка</b>"}).status_code == 201
        assert operator.post(notes, headers=HEADERS, json={"text": "Вторая заметка"}).status_code == 201
        assert operator.post(reset).status_code == 403
        assert operator.put("/api/admin/limits", headers=HEADERS, json={
            "target": "account", "account_id": account, "maximum": 3,
        }).status_code == 200
        assert current.get("/api/beta/quota").json()["remaining"] == 2
        updated = operator.post(reset, headers=HEADERS).json()
        assert updated["global"] == {"used": 1, "limit": 10, "remaining": 9}
        row = updated["accounts"][0]
        assert (row["used"], row["limit"], row["remaining"], row["custom"]) == (0, 3, 3, True)
        assert [note["text"] for note in row["notes"]] == ["Вторая заметка", "<b>Личная заметка</b>"]
        quota = current.get("/api/beta/quota").json()
        assert quota == {"limit": 3, "remaining": 3, "reset_at": updated["reset_at"]}
        assert "notes" not in current.get("/api/config").json()
        assert operator.post(invites, headers=HEADERS, json={"label": "New", "hours": 0}).status_code == 422
        invite = operator.post(invites, headers=HEADERS, json={"label": "New", "hours": 2})
        assert invite.status_code == 201 and invite.headers["cache-control"] == "no-store"
        code = invite.json()["code"]
        accounts = operator.get("/api/admin/usage")
        assert code not in accounts.text
        assert next(item for item in accounts.json()["accounts"] if item["id"] == invite.json()["account_id"])["notes"] == []
        assert invited.post("/api/beta/redeem", headers=HEADERS, json={"code": code}).status_code == 200
        assert invited.post("/api/beta/logout", headers=HEADERS).status_code == 200
        assert invited.post("/api/beta/redeem", headers=HEADERS, json={"code": code}).status_code == 400
