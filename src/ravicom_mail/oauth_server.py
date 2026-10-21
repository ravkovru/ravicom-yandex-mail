"""Per-user OAuth 2.1 authorization server for ChatGPT and Yandex Mail."""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import sqlite3
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from threading import RLock
from typing import Any
from urllib.parse import urlencode

import httpx
from cryptography.fernet import Fernet
from mcp.server.auth.provider import (
    AccessToken, AuthorizationCode, AuthorizationParams, AuthorizeError,
    OAuthAuthorizationServerProvider, RefreshToken, RegistrationError, TokenError,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken

YANDEX_AUTHORIZE = "https://oauth.yandex.com/authorize"
YANDEX_TOKEN = "https://oauth.yandex.com/token"
MAIL_SCOPE = "mail:imap_full"


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


@dataclass
class PendingAuthorization:
    state: str
    client_id: str
    redirect_uri: str
    client_state: str | None
    code_challenge: str
    scopes: list[str]
    resource: str | None
    expires_at: float
    yandex_access: str | None = None
    yandex_refresh: str | None = None
    yandex_expires_at: float | None = None


class OAuthStore:
    """Small persistent store suitable for a single hosted service instance."""

    def __init__(self, database_url: str, encryption_key: str):
        if not encryption_key:
            raise ValueError("TOKEN_ENCRYPTION_KEY is required")
        self.cipher = Fernet(encryption_key.encode())
        self.path = database_url.removeprefix("sqlite:///")
        if self.path == database_url or self.path in {"", ":memory:"}:
            raise ValueError("DATABASE_URL must be a persistent sqlite:/// path")
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.lock = RLock()
        with self._db() as db:
            db.executescript("""
              PRAGMA journal_mode=WAL;
              CREATE TABLE IF NOT EXISTS clients (client_id TEXT PRIMARY KEY, body TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS pending (state TEXT PRIMARY KEY, body TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS mailboxes (
                subject TEXT PRIMARY KEY, email TEXT NOT NULL,
                access_token BLOB NOT NULL, refresh_token BLOB,
                expires_at REAL, created_at REAL NOT NULL
              );
              CREATE TABLE IF NOT EXISTS auth_codes (token_hash TEXT PRIMARY KEY, body TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS access_tokens (token_hash TEXT PRIMARY KEY, body TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS refresh_tokens (token_hash TEXT PRIMARY KEY, body TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS cleanup_previews (
                preview_id TEXT PRIMARY KEY, subject TEXT NOT NULL, body TEXT NOT NULL,
                created_at REAL NOT NULL
              );
            """)

    def _db(self):
        db = sqlite3.connect(self.path, timeout=15, check_same_thread=False)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA busy_timeout=15000")
        return db

    def encrypt(self, value: str | None):
        return self.cipher.encrypt(value.encode()) if value else None

    def decrypt(self, value: bytes | None):
        return self.cipher.decrypt(value).decode() if value else None

    def put_json(self, table: str, key: str, value: dict[str, Any]):
        if table not in {"clients", "pending", "auth_codes", "access_tokens", "refresh_tokens"}:
            raise ValueError("unsupported table")
        with self.lock, self._db() as db:
            db.execute(f"INSERT OR REPLACE INTO {table} VALUES (?, ?)", (key, json.dumps(value)))

    def get_json(self, table: str, key: str):
        if table not in {"clients", "pending", "auth_codes", "access_tokens", "refresh_tokens"}:
            raise ValueError("unsupported table")
        with self.lock, self._db() as db:
            row = db.execute(f"SELECT body FROM {table} WHERE {('client_id' if table == 'clients' else 'state' if table == 'pending' else 'token_hash')}=?", (key,)).fetchone()
            return json.loads(row[0]) if row else None

    def delete(self, table: str, key: str):
        if table not in {"pending", "auth_codes", "access_tokens", "refresh_tokens"}:
            raise ValueError("unsupported table")
        column = "state" if table == "pending" else "token_hash"
        with self.lock, self._db() as db:
            db.execute(f"DELETE FROM {table} WHERE {column}=?", (key,))

    def save_mailbox(self, subject: str, email: str, access: str, refresh: str | None, expires_at: float | None):
        with self.lock, self._db() as db:
            db.execute("""INSERT INTO mailboxes(subject,email,access_token,refresh_token,expires_at,created_at)
              VALUES(?,?,?,?,?,?) ON CONFLICT(subject) DO UPDATE SET email=excluded.email,
              access_token=excluded.access_token,refresh_token=excluded.refresh_token,expires_at=excluded.expires_at""",
              (subject, email, self.encrypt(access), self.encrypt(refresh), expires_at, time.time()))

    def mailbox(self, subject: str):
        with self.lock, self._db() as db:
            row = db.execute("SELECT * FROM mailboxes WHERE subject=?", (subject,)).fetchone()
        if not row:
            return None
        return {"subject": row["subject"], "email": row["email"], "access_token": self.decrypt(row["access_token"]),
                "refresh_token": self.decrypt(row["refresh_token"]), "expires_at": row["expires_at"]}

    def save_preview(self, preview_id: str, subject: str, data: dict[str, Any]):
        with self.lock, self._db() as db:
            db.execute("INSERT OR REPLACE INTO cleanup_previews VALUES(?,?,?,?)", (preview_id, subject, json.dumps(data), time.time()))

    def take_preview(self, preview_id: str, subject: str):
        with self.lock, self._db() as db:
            row = db.execute("SELECT body,created_at FROM cleanup_previews WHERE preview_id=? AND subject=?", (preview_id, subject)).fetchone()
            db.execute("DELETE FROM cleanup_previews WHERE preview_id=? AND subject=?", (preview_id, subject))
        if not row or time.time() - row[1] > 900:
            return None
        return json.loads(row[0])

    def delete_subject_data(self, subject: str):
        """Remove a mailbox and all OAuth grants tied to its connection."""
        with self.lock, self._db() as db:
            db.execute("DELETE FROM mailboxes WHERE subject=?", (subject,))
            db.execute("DELETE FROM cleanup_previews WHERE subject=?", (subject,))
            for table in ("access_tokens", "refresh_tokens", "auth_codes"):
                rows = db.execute(f"SELECT token_hash,body FROM {table}").fetchall()
                for row in rows:
                    if json.loads(row["body"]).get("subject") == subject:
                        db.execute(f"DELETE FROM {table} WHERE token_hash=?", (row["token_hash"],))


class YandexOAuthProvider(OAuthAuthorizationServerProvider[AuthorizationCode, RefreshToken, AccessToken]):
    def __init__(self, store: OAuthStore, public_base_url: str, yandex_client_id: str, yandex_client_secret: str):
        self.store = store
        self.base_url = public_base_url.rstrip("/")
        self.client_id = yandex_client_id
        self.client_secret = yandex_client_secret

    async def get_client(self, client_id: str):
        body = self.store.get_json("clients", client_id)
        return OAuthClientInformationFull.model_validate(body) if body else None

    async def register_client(self, client_info: OAuthClientInformationFull):
        if not client_info.client_id:
            raise RegistrationError("invalid_client_metadata", "Client ID is required")
        self.store.put_json("clients", client_info.client_id, client_info.model_dump(mode="json"))

    async def authorize(self, client: OAuthClientInformationFull, params: AuthorizationParams) -> str:
        requested = params.scopes or ["mail:read", "mail:manage"]
        allowed = {"mail:read", "mail:manage"}
        if not set(requested).issubset(allowed) or "mail:read" not in requested:
            raise AuthorizeError("invalid_scope", "RAVICOM Mail supports mail:read and mail:manage")
        state = secrets.token_urlsafe(32)
        pending = PendingAuthorization(
            state=state, client_id=client.client_id or "", redirect_uri=str(params.redirect_uri),
            client_state=params.state, code_challenge=params.code_challenge,
            scopes=requested, resource=params.resource, expires_at=time.time() + 600,
        )
        self.store.put_json("pending", state, asdict(pending))
        query = urlencode({
            "response_type": "code", "client_id": self.client_id,
            "redirect_uri": self.base_url + "/oauth/yandex/callback", "scope": MAIL_SCOPE,
            "state": state, "force_confirm": "yes",
        })
        return f"{YANDEX_AUTHORIZE}?{query}"

    async def complete_yandex(self, state: str, code: str):
        data = self.store.get_json("pending", state)
        if not data or data["expires_at"] < time.time():
            self.store.delete("pending", state)
            raise ValueError("Authorization expired. Start connecting again.")
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(YANDEX_TOKEN, data={
                "grant_type": "authorization_code", "code": code, "client_id": self.client_id,
                "client_secret": self.client_secret,
                "redirect_uri": self.base_url + "/oauth/yandex/callback",
            })
        if response.is_error:
            raise ValueError("Yandex authorization could not be completed. Start again.")
        token_data = response.json()
        if not token_data.get("access_token"):
            raise ValueError("Yandex did not issue a mail access token.")
        data["yandex_access"] = token_data["access_token"]
        data["yandex_refresh"] = token_data.get("refresh_token")
        data["yandex_expires_at"] = time.time() + int(token_data.get("expires_in", 31536000))
        self.store.put_json("pending", state, data)
        return data

    async def finish_yandex(self, state: str, email: str):
        data = self.store.get_json("pending", state)
        if not data or data["expires_at"] < time.time() or not data.get("yandex_access"):
            self.store.delete("pending", state)
            raise ValueError("Authorization expired. Start connecting again.")
        email = email.strip()
        if len(email) > 254 or "@" not in email or any(c in email for c in "\r\n\x00"):
            raise ValueError("Enter a valid Yandex mailbox address.")
        subject = secrets.token_urlsafe(24)
        self.store.save_mailbox(subject, email, data["yandex_access"], data.get("yandex_refresh"), data.get("yandex_expires_at"))
        code = secrets.token_urlsafe(32)
        auth = AuthorizationCode(
            code=code, scopes=data["scopes"], expires_at=time.time() + 300,
            client_id=data["client_id"], code_challenge=data["code_challenge"],
            redirect_uri=data["redirect_uri"], redirect_uri_provided_explicitly=True,
            resource=data.get("resource"), subject=subject,
        )
        self.store.put_json("auth_codes", _hash(code), auth.model_dump(mode="json"))
        self.store.delete("pending", state)
        return data["redirect_uri"], code, data.get("client_state")

    async def load_authorization_code(self, client: OAuthClientInformationFull, authorization_code: str):
        data = self.store.get_json("auth_codes", _hash(authorization_code))
        return AuthorizationCode.model_validate(data) if data and data["client_id"] == client.client_id else None

    async def exchange_authorization_code(self, client: OAuthClientInformationFull, authorization_code: AuthorizationCode):
        self.store.delete("auth_codes", _hash(authorization_code.code))
        access, refresh = secrets.token_urlsafe(32), secrets.token_urlsafe(40)
        body = {"client_id": client.client_id, "scopes": authorization_code.scopes,
                "subject": authorization_code.subject, "resource": authorization_code.resource,
                "expires_at": time.time() + 3600}
        self.store.put_json("access_tokens", _hash(access), body)
        self.store.put_json("refresh_tokens", _hash(refresh), {**body, "expires_at": time.time() + 90 * 86400})
        return OAuthToken(access_token=access, refresh_token=refresh, expires_in=3600, scope=" ".join(body["scopes"]))

    async def load_refresh_token(self, client: OAuthClientInformationFull, refresh_token: str):
        data = self.store.get_json("refresh_tokens", _hash(refresh_token))
        if not data or data["client_id"] != client.client_id or data["expires_at"] < time.time():
            return None
        return RefreshToken(token=refresh_token, client_id=client.client_id or "", scopes=data["scopes"],
                            expires_at=int(data["expires_at"]), resource=data.get("resource"), subject=data.get("subject"))

    async def exchange_refresh_token(self, client: OAuthClientInformationFull, refresh_token: RefreshToken, scopes: list[str]):
        self.store.delete("refresh_tokens", _hash(refresh_token.token))
        granted = scopes or refresh_token.scopes
        if not set(granted).issubset(refresh_token.scopes):
            raise TokenError("invalid_scope", "Cannot expand scopes during refresh")
        access, new_refresh = secrets.token_urlsafe(32), secrets.token_urlsafe(40)
        body = {"client_id": client.client_id, "scopes": granted, "subject": refresh_token.subject,
                "resource": refresh_token.resource, "expires_at": time.time() + 3600}
        self.store.put_json("access_tokens", _hash(access), body)
        self.store.put_json("refresh_tokens", _hash(new_refresh), {**body, "expires_at": time.time() + 90 * 86400})
        return OAuthToken(access_token=access, refresh_token=new_refresh, expires_in=3600, scope=" ".join(granted))

    async def load_access_token(self, token: str):
        data = self.store.get_json("access_tokens", _hash(token))
        if not data or data["expires_at"] < time.time():
            return None
        return AccessToken(token=token, client_id=data["client_id"], scopes=data["scopes"],
                           expires_at=int(data["expires_at"]), resource=data.get("resource"), subject=data.get("subject"))

    async def revoke_token(self, token: AccessToken | RefreshToken):
        if token.subject:
            self.store.delete_subject_data(token.subject)
        else:
            table = "access_tokens" if isinstance(token, AccessToken) else "refresh_tokens"
            self.store.delete(table, _hash(token.token))

    async def get_mailbox(self, subject: str):
        mailbox = self.store.mailbox(subject)
        if mailbox and mailbox["expires_at"] and mailbox["expires_at"] < time.time() + 120 and mailbox["refresh_token"]:
            async with httpx.AsyncClient(timeout=20) as client:
                response = await client.post(YANDEX_TOKEN, data={
                    "grant_type": "refresh_token", "refresh_token": mailbox["refresh_token"],
                    "client_id": self.client_id, "client_secret": self.client_secret,
                })
            if response.is_error or not response.json().get("access_token"):
                raise ValueError("Yandex authorization expired; reconnect this mailbox.")
            data = response.json()
            self.store.save_mailbox(subject, mailbox["email"], data["access_token"],
                data.get("refresh_token", mailbox["refresh_token"]), time.time() + int(data.get("expires_in", 31536000)))
            mailbox = self.store.mailbox(subject)
        return mailbox
