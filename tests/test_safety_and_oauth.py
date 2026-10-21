import pytest
from starlette.testclient import TestClient
from ravicom_mail.oauth import OAuthError, access_token
from ravicom_mail import server

def test_cleanup_needs_exact_confirmation():
    with pytest.raises(ValueError,match="Explicit confirmation"):
        server.execute_cleanup("missing","yes")

def test_cleanup_preview_requires_minimum_age():
    with pytest.raises(ValueError,match="at least 30"):
        server.cleanup_preview(older_than_days=2)

def test_preview_moves_to_trash_once(monkeypatch):
    server.PREVIEWS["abc"]={"folder":"INBOX","uids":["1"],"created":9999999999}
    calls=[]
    monkeypatch.setattr(server,"_run",lambda fn:fn(object()))
    monkeypatch.setattr(server.mail,"move",lambda c,src,dst,uids:calls.append((src,dst,uids)) or {"moved":len(uids)})
    assert server.execute_cleanup("abc","MOVE TO TRASH")=={"moved":1}
    assert calls==[("INBOX","Trash",["1"])]
    assert "abc" not in server.PREVIEWS

def test_missing_token_is_clear(monkeypatch):
    monkeypatch.delenv("YANDEX_ACCESS_TOKEN",raising=False)
    with pytest.raises(OAuthError,match="YANDEX_ACCESS_TOKEN"):
        access_token()

def test_http_health_is_public_and_contains_no_mailbox_data(monkeypatch):
    monkeypatch.delenv("MCP_BEARER_TOKEN", raising=False)
    with TestClient(server.create_http_app()) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "RAVICOM Mail for Yandex"}

def test_http_transport_requires_bearer_token(monkeypatch):
    monkeypatch.setenv("MCP_BEARER_TOKEN", "test-secret")
    response = TestClient(server.create_http_app()).post("/mcp", json={})
    assert response.status_code == 401
    assert response.headers["www-authenticate"].startswith("Bearer")

def test_http_transport_fails_closed_without_configured_secret(monkeypatch):
    monkeypatch.delenv("MCP_BEARER_TOKEN", raising=False)
    response = TestClient(server.create_http_app()).post(
        "/mcp", headers={"Authorization": "Bearer anything"}, json={}
    )
    assert response.status_code == 503
