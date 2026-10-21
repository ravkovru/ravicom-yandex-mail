import pytest
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
