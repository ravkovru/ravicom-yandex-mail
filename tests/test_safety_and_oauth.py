import pytest
from starlette.testclient import TestClient
from cryptography.fernet import Fernet
from ravicom_mail.oauth import OAuthError, access_token
from ravicom_mail import server
from ravicom_mail.oauth_server import OAuthStore


class _CreateFolderClient:
    def __init__(self, response=("OK", [b"created"])):
        self.response = response
        self.calls = []

    def create(self, folder):
        self.calls.append(folder)
        return self.response

def test_cleanup_needs_exact_confirmation():
    with pytest.raises(ValueError,match="Explicit confirmation"):
        server.execute_cleanup("missing","yes")


def test_create_folder_calls_imap_and_returns_name():
    client = _CreateFolderClient()
    assert server.mail.create_folder(client, "Projects") == {
        "created": True,
        "folder": "Projects",
    }
    assert client.calls == ["Projects"]


def test_create_folder_rejects_empty_name():
    with pytest.raises(server.mail.MailError, match="between 1 and 120"):
        server.mail.create_folder(_CreateFolderClient(), "  ")

def test_cleanup_preview_requires_minimum_age():
    with pytest.raises(ValueError,match="at least 30"):
        server.cleanup_preview(older_than_days=2)

def test_cleanup_preview_is_persistent_and_user_scoped(tmp_path):
    store = OAuthStore(f"sqlite:///{tmp_path / 'test.db'}", Fernet.generate_key().decode())
    store.save_preview("abc", "user-a", {"folder": "INBOX", "uids": ["1"]})
    assert store.take_preview("abc", "user-b") is None
    assert store.take_preview("abc", "user-a") == {"folder": "INBOX", "uids": ["1"]}
    assert store.take_preview("abc", "user-a") is None


def test_local_cleanup_preview_moves_to_trash_once(monkeypatch):
    server._local_previews.clear()
    calls = []
    monkeypatch.setattr(server, "_run", lambda fn: fn(object()))
    monkeypatch.setattr(server.mail, "search", lambda *args, **kwargs: [{"uid": "1"}])
    monkeypatch.setattr(server.mail, "move", lambda c, src, dst, uids: calls.append((src, dst, uids)) or {"moved": len(uids)})
    preview = server.cleanup_preview()
    assert preview["count"] == 1
    assert server.execute_cleanup(preview["preview_id"], "MOVE TO TRASH") == {"moved": 1}
    assert calls == [("INBOX", "Trash", ["1"])]
    with pytest.raises(ValueError, match="Preview missing"):
        server.execute_cleanup(preview["preview_id"], "MOVE TO TRASH")

def test_missing_token_is_clear(monkeypatch):
    monkeypatch.delenv("YANDEX_ACCESS_TOKEN",raising=False)
    with pytest.raises(OAuthError,match="YANDEX_ACCESS_TOKEN"):
        access_token()

def test_public_http_requires_oauth_configuration(monkeypatch):
    for key in ("PUBLIC_BASE_URL", "YANDEX_CLIENT_ID", "YANDEX_CLIENT_SECRET", "TOKEN_ENCRYPTION_KEY"):
        monkeypatch.delenv(key, raising=False)
    with pytest.raises(RuntimeError, match="Public OAuth configuration missing"):
        server.create_http_app()


def test_public_http_requires_https_and_privacy_contact(monkeypatch):
    monkeypatch.setenv("YANDEX_CLIENT_ID", "test-client")
    monkeypatch.setenv("YANDEX_CLIENT_SECRET", "test-secret")
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("PRIVACY_CONTACT_EMAIL", "privacy@example.com")
    monkeypatch.setenv("PUBLIC_BASE_URL", "http://mail.example.com")
    with pytest.raises(RuntimeError, match="public HTTPS"):
        server.create_http_app()


def test_render_external_url_can_supply_public_base(monkeypatch, tmp_path):
    monkeypatch.delenv("PUBLIC_BASE_URL", raising=False)
    monkeypatch.setenv("RENDER_EXTERNAL_URL", "https://mail.example.com/")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'mail.db'}")
    monkeypatch.setenv("YANDEX_CLIENT_ID", "test-client")
    monkeypatch.setenv("YANDEX_CLIENT_SECRET", "test-secret")
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("PRIVACY_CONTACT_EMAIL", "privacy@example.com")
    app = server.create_http_app()
    assert app is not None
    assert server._provider.base_url == "https://mail.example.com"


def test_public_endpoints_are_live_and_mcp_requires_oauth(monkeypatch, tmp_path):
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://mail.example.com")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'http.db'}")
    monkeypatch.setenv("YANDEX_CLIENT_ID", "test-client")
    monkeypatch.setenv("YANDEX_CLIENT_SECRET", "test-secret")
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("PRIVACY_CONTACT_EMAIL", "privacy@example.com")
    app = server.create_http_app()
    with TestClient(app, base_url="https://mail.example.com") as client:
        assert client.get("/health").status_code == 200
        assert client.get("/privacy").status_code == 200
        assert client.get("/.well-known/oauth-authorization-server").status_code == 200
        assert client.get("/.well-known/oauth-protected-resource/mcp").status_code == 200
        assert client.post("/mcp", json={}).status_code == 401


def test_public_product_pages_and_challenge(monkeypatch, tmp_path):
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://mail.example.com")
    monkeypatch.setenv("YANDEX_CLIENT_ID", "client")
    monkeypatch.setenv("YANDEX_CLIENT_SECRET", "secret")
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("PRIVACY_CONTACT_EMAIL", "privacy@example.com")
    monkeypatch.setenv("OPENAI_APPS_CHALLENGE", "challenge-token")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'pages.db'}")
    app = server.create_http_app()
    with TestClient(app, base_url="https://mail.example.com") as client:
        assert client.get("/terms").status_code == 200
        assert client.get("/support").status_code == 200
        assert client.get("/.well-known/openai-apps-challenge").text == "challenge-token"


def test_mailbox_tokens_are_encrypted_at_rest(tmp_path):
    key = Fernet.generate_key().decode()
    store = OAuthStore(f"sqlite:///{tmp_path / 'test.db'}", key)
    store.save_mailbox("subject-1", "person@yandex.ru", "yandex-access-secret", "refresh-secret", 9999999999)
    raw = (tmp_path / "test.db").read_bytes()
    assert b"yandex-access-secret" not in raw
    assert store.mailbox("subject-1")["access_token"] == "yandex-access-secret"


def test_revoking_connection_removes_tokens_and_previews(tmp_path):
    store = OAuthStore(f"sqlite:///{tmp_path / 'test.db'}", Fernet.generate_key().decode())
    store.save_mailbox("subject-1", "person@yandex.ru", "access", "refresh", 9999999999)
    store.put_json("access_tokens", "access-hash", {"subject": "subject-1", "scopes": ["mail:read"]})
    store.put_json("refresh_tokens", "refresh-hash", {"subject": "subject-1", "scopes": ["mail:read"]})
    store.save_preview("preview", "subject-1", {"folder": "INBOX", "uids": ["1"]})
    store.delete_subject_data("subject-1")
    assert store.mailbox("subject-1") is None
    assert store.get_json("access_tokens", "access-hash") is None
    assert store.get_json("refresh_tokens", "refresh-hash") is None
    assert store.take_preview("preview", "subject-1") is None
