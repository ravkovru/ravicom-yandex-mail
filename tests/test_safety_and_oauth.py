import pytest
from cryptography.fernet import Fernet
from ravicom_mail.oauth import OAuthError, access_token
from ravicom_mail import server
from ravicom_mail.oauth_server import OAuthStore

def test_cleanup_needs_exact_confirmation():
    with pytest.raises(ValueError,match="Explicit confirmation"):
        server.execute_cleanup("missing","yes")

def test_cleanup_preview_requires_minimum_age():
    with pytest.raises(ValueError,match="at least 30"):
        server.cleanup_preview(older_than_days=2)

def test_cleanup_preview_is_persistent_and_user_scoped(tmp_path):
    store = OAuthStore(f"sqlite:///{tmp_path / 'test.db'}", Fernet.generate_key().decode())
    store.save_preview("abc", "user-a", {"folder": "INBOX", "uids": ["1"]})
    assert store.take_preview("abc", "user-b") is None
    assert store.take_preview("abc", "user-a") == {"folder": "INBOX", "uids": ["1"]}
    assert store.take_preview("abc", "user-a") is None

def test_missing_token_is_clear(monkeypatch):
    monkeypatch.delenv("YANDEX_ACCESS_TOKEN",raising=False)
    with pytest.raises(OAuthError,match="YANDEX_ACCESS_TOKEN"):
        access_token()

def test_public_http_requires_oauth_configuration(monkeypatch):
    for key in ("PUBLIC_BASE_URL", "YANDEX_CLIENT_ID", "YANDEX_CLIENT_SECRET", "TOKEN_ENCRYPTION_KEY"):
        monkeypatch.delenv(key, raising=False)
    with pytest.raises(RuntimeError, match="Public OAuth configuration missing"):
        server.create_http_app()


def test_mailbox_tokens_are_encrypted_at_rest(tmp_path):
    key = Fernet.generate_key().decode()
    store = OAuthStore(f"sqlite:///{tmp_path / 'test.db'}", key)
    store.save_mailbox("subject-1", "person@yandex.ru", "yandex-access-secret", "refresh-secret", 9999999999)
    raw = (tmp_path / "test.db").read_bytes()
    assert b"yandex-access-secret" not in raw
    assert store.mailbox("subject-1")["access_token"] == "yandex-access-secret"
