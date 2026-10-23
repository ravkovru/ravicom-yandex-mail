"""MCP service for Yandex Mail, with per-user OAuth in remote mode."""
from __future__ import annotations

import hashlib
import html
import os
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import httpx
from dotenv import load_dotenv
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions
from mcp.server.fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse

from . import imap_client as mail
from .oauth_server import OAuthStore, YandexOAuthProvider

load_dotenv()

_store: OAuthStore | None = None
_provider: YandexOAuthProvider | None = None
_local_previews: dict[str, dict] = {}


def _mailbox_credentials() -> tuple[str | None, str | None]:
    """Return this request's connected mailbox, never another user's credentials."""
    token = get_access_token()
    if token is None:
        return os.getenv("YANDEX_EMAIL"), None
    if _store is None or not token.subject:
        raise RuntimeError("Mailbox connection is unavailable; reconnect Yandex Mail")
    row = _store.mailbox(token.subject)
    if not row:
        raise RuntimeError("Yandex Mail is not connected; reconnect your mailbox")
    if row["expires_at"] and row["expires_at"] < time.time() + 120:
        if not row["refresh_token"]:
            raise RuntimeError("Yandex access expired; reconnect your mailbox")
        response = httpx.post("https://oauth.yandex.com/token", data={
            "grant_type": "refresh_token", "refresh_token": row["refresh_token"],
            "client_id": os.environ["YANDEX_CLIENT_ID"],
            "client_secret": os.environ["YANDEX_CLIENT_SECRET"],
        }, timeout=20)
        if response.is_error:
            raise RuntimeError("Yandex access expired; reconnect your mailbox")
        data = response.json()
        _store.save_mailbox(token.subject, row["email"], data["access_token"],
                            data.get("refresh_token", row["refresh_token"]),
                            time.time() + int(data.get("expires_in", 3600)))
        row = _store.mailbox(token.subject)
    return row["email"], row["access_token"]


def _connection():
    email, access = _mailbox_credentials()
    return mail.connect(os.getenv("YANDEX_IMAP_HOST", "imap.yandex.ru"),
                        int(os.getenv("YANDEX_IMAP_PORT", "993")), user=email, token=access)


def _require_manage():
    token = get_access_token()
    if token is not None and "mail:manage" not in token.scopes:
        raise PermissionError("This action requires the mail:manage permission. Reconnect and approve it in ChatGPT.")


def _run(fn):
    client = _connection()
    try:
        return fn(client)
    finally:
        client.logout()


def list_folders() -> list[dict]:
    """List mailbox folders and IMAP flags."""
    return _run(mail.folders)


def create_folder(folder_name: str) -> dict:
    """Create a new mailbox folder."""
    _require_manage()
    return _run(lambda c: mail.create_folder(c, folder_name))


def mailbox_stats() -> dict:
    """Return mailbox folder, message, and unread counts."""
    def read(client):
        result = []
        for folder in mail.folders(client):
            try:
                typ, data = client.select(folder["name"], readonly=True)
                if typ != "OK":
                    continue
                total = int(data[0]); typ, unseen = client.search(None, "UNSEEN")
                unread = len(unseen[0].split()) if typ == "OK" and unseen and unseen[0] else 0
                result.append({"folder": folder["name"], "total": total, "unread": unread})
            except Exception:
                continue
        return {"folders": result, "total": sum(x["total"] for x in result),
                "unread": sum(x["unread"] for x in result)}
    return _run(read)


def search_mail(folder: str = "INBOX", from_addr: str | None = None, subject: str | None = None,
                since: str | None = None, before: str | None = None,
                unread: bool | None = None, limit: int = 50) -> list[dict]:
    """Search by folder, sender, subject, dates (DD-Mon-YYYY), and read state."""
    return _run(lambda c: mail.search(c, folder, from_addr, subject, since, before, unread, limit))


def read_message(folder: str, uid: str) -> dict:
    """Read one message by IMAP UID and folder."""
    return _run(lambda c: mail.read_message(c, folder, uid))


def mark_read(folder: str, uids: list[str]) -> dict:
    """Mark messages as read."""
    _require_manage()
    return _run(lambda c: mail.set_read(c, folder, uids, True))


def mark_unread(folder: str, uids: list[str]) -> dict:
    """Mark messages as unread."""
    _require_manage()
    return _run(lambda c: mail.set_read(c, folder, uids, False))


def move_messages(source_folder: str, destination_folder: str, uids: list[str]) -> dict:
    """Move messages between folders."""
    _require_manage()
    return _run(lambda c: mail.move(c, source_folder, destination_folder, uids))


def cleanup_preview(folder: str = "INBOX", older_than_days: int = 365, limit: int = 500) -> dict:
    """Preview old read messages proposed for Trash. This makes no mailbox changes."""
    if older_than_days < 30:
        raise ValueError("older_than_days must be at least 30")
    if not 1 <= limit <= 500:
        raise ValueError("limit must be between 1 and 500")
    before = (datetime.now(timezone.utc) - timedelta(days=older_than_days)).strftime("%d-%b-%Y")
    messages = _run(lambda c: mail.search(c, folder, before=before, unread=False, limit=limit))
    preview_id = hashlib.sha256(os.urandom(32)).hexdigest()[:24]
    token = get_access_token()
    if token and _store and token.subject:
        _store.save_preview(preview_id, token.subject,
                            {"folder": folder, "uids": [m["uid"] for m in messages]})
    else:
        _local_previews[preview_id] = {"folder": folder, "uids": [m["uid"] for m in messages],
                                       "created": time.time()}
    return {"preview_id": preview_id, "folder": folder, "count": len(messages),
            "messages": messages, "expires_in_seconds": 900}


def execute_cleanup(preview_id: str, confirmation: str) -> dict:
    """Move a user's unexpired cleanup preview to Trash after exact confirmation."""
    if confirmation != "MOVE TO TRASH":
        raise ValueError("Explicit confirmation required: MOVE TO TRASH")
    _require_manage()
    token = get_access_token()
    if token and _store and token.subject:
        plan = _store.take_preview(preview_id, token.subject)
    else:
        plan = _local_previews.pop(preview_id, None)
        if plan and time.time() - plan["created"] > 900:
            plan = None
    if not plan:
        raise ValueError("Preview missing, expired, or belongs to another user")
    return _run(lambda c: mail.move(c, plan["folder"], "Trash", plan["uids"])) if plan["uids"] else {"moved": 0, "to": "Trash"}


def _new_mcp(remote: bool = False) -> FastMCP:
    global _store, _provider
    kwargs = {}
    if remote:
        base = os.environ["PUBLIC_BASE_URL"].rstrip("/")
        _store = OAuthStore(os.environ.get("DATABASE_URL", "sqlite:////data/ravicom-mail.sqlite3"),
                            os.environ["TOKEN_ENCRYPTION_KEY"])
        _provider = YandexOAuthProvider(_store, base, os.environ["YANDEX_CLIENT_ID"],
                                        os.environ["YANDEX_CLIENT_SECRET"])
        # The protected resource is the actual MCP endpoint.  Advertising the
        # site root here makes RFC 9728 discovery ambiguous for clients that
        # connect to /mcp and expect path-specific resource metadata.
        resource_url = f"{base}/mcp"
        kwargs = {
            "auth_server_provider": _provider,
            "auth": AuthSettings(issuer_url=base, resource_server_url=resource_url,
                                 required_scopes=["mail:read", "mail:manage"], validate_token_resource=True,
                                 client_registration_options=ClientRegistrationOptions(
                                     enabled=True, valid_scopes=["mail:read", "mail:manage"],
                                     default_scopes=["mail:read", "mail:manage"])),
        }
    server = FastMCP("RAVICOM Mail for Yandex", **kwargs)
    for tool in (list_folders, create_folder, mailbox_stats, search_mail, read_message, mark_read,
                 mark_unread, move_messages, cleanup_preview, execute_cleanup):
        server.add_tool(tool)
    return server


def create_http_app():
    """Create public OAuth-protected Streamable HTTP app."""
    global _store, _provider
    required = ("YANDEX_CLIENT_ID", "YANDEX_CLIENT_SECRET", "TOKEN_ENCRYPTION_KEY", "PRIVACY_CONTACT_EMAIL")
    missing = [key for key in required if not os.getenv(key)]
    if missing:
        raise RuntimeError("Public OAuth configuration missing: " + ", ".join(missing))
    base = os.getenv("PUBLIC_BASE_URL") or os.getenv("RENDER_EXTERNAL_URL", "")
    if not base.startswith("https://"):
        raise RuntimeError("PUBLIC_BASE_URL must be the public HTTPS service URL")
    os.environ["PUBLIC_BASE_URL"] = base.rstrip("/")
    app_mcp = _new_mcp(remote=True)
    @app_mcp.custom_route("/health", methods=["GET"], include_in_schema=False)
    async def health(_: Request):
        return JSONResponse({"status": "ok", "service": "RAVICOM Mail for Yandex"})

    @app_mcp.custom_route("/oauth/yandex/callback", methods=["GET", "POST"], include_in_schema=False)
    async def yandex_callback(request: Request):
        global _provider
        if request.method == "POST":
            form = await request.form(); state = str(form.get("state", "")); email = str(form.get("email", ""))
            try:
                redirect, code, client_state = await _provider.finish_yandex(state, email)
            except (ValueError, AttributeError):
                return HTMLResponse("<h1>Connection expired</h1><p>Close this page and connect again from ChatGPT.</p>", status_code=400)
            query = {"code": code}
            if client_state:
                query["state"] = client_state
            return RedirectResponse(redirect + "?" + urlencode(query), status_code=303)
        code, state = request.query_params.get("code"), request.query_params.get("state", "")
        if request.query_params.get("error"):
            return HTMLResponse("<h1>Yandex access was not granted</h1><p>Close this page and try again when ready.</p>", status_code=400)
        if not code or not _provider:
            return HTMLResponse("<h1>Invalid Yandex callback</h1>", status_code=400)
        try:
            await _provider.complete_yandex(state, code)
        except (ValueError, httpx.HTTPError):
            return HTMLResponse("<h1>Could not connect Yandex Mail</h1><p>Close this page and connect again from ChatGPT.</p>", status_code=400)
        safe_state = html.escape(state, quote=True)
        return HTMLResponse(f"""<!doctype html><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Connect Yandex Mail</title><main style="font:16px system-ui;max-width:440px;margin:12vh auto;padding:24px">
<h1>Connect Yandex Mail</h1><p>Enter the mailbox address you authorized. This address is used only for IMAP access.</p>
<form method="post"><input type="hidden" name="state" value="{safe_state}">
<label>Yandex mailbox<input name="email" type="email" autocomplete="email" required style="display:block;width:100%;padding:12px;margin:8px 0 16px"></label>
<button style="padding:12px 18px">Continue to ChatGPT</button></form></main>""")

    @app_mcp.custom_route("/", methods=["GET"], include_in_schema=False)
    async def root(_: Request):
        return JSONResponse({"service": "RAVICOM Mail for Yandex", "mcp": "/mcp", "health": "/health"})

    @app_mcp.custom_route("/privacy", methods=["GET"], include_in_schema=False)
    async def privacy(_: Request):
        contact = html.escape(os.getenv("PRIVACY_CONTACT_EMAIL", ""))
        if not contact:
            return HTMLResponse("Privacy contact is not configured.", status_code=503)
        return HTMLResponse(f"""<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>RAVICOM Mail Privacy Policy</title>
<main style="font:16px/1.6 system-ui;max-width:760px;margin:48px auto;padding:0 20px">
<h1>RAVICOM Mail Privacy Policy</h1><p>Effective date: 22 October 2026</p>
<p>RAVICOM Mail is an MCP service that lets a user connect their own Yandex Mail account to ChatGPT. The service processes mailbox requests only to provide the tools selected by the user.</p>
<h2>Information processed</h2><p>When you connect, the service receives Yandex OAuth access and refresh tokens, the mailbox address you enter, and OAuth connection metadata. When you use a tool, the service temporarily processes the messages and mailbox information needed to answer that request. Message bodies are not written to the service database. A cleanup preview stores folder names and message UIDs until used or the connection is revoked; the preview can only be executed for 15 minutes.</p>
<h2>How information is used and shared</h2><p>OAuth tokens are encrypted in the service database and used only to access the connected mailbox through Yandex IMAP. Mailbox content returned by a tool is sent to ChatGPT to fulfill your request and is subject to the data handling terms and settings of your ChatGPT account. RAVICOM Mail does not sell mailbox data, use it for advertising, send messages, or permanently delete messages.</p>
<h2>Retention and deletion</h2><p>Mailbox tokens and address are retained while the connection is active. Disconnect or revoke RAVICOM Mail in ChatGPT to delete the connection's tokens, address, and pending cleanup previews. Expired previews are unusable after 15 minutes. Operational security logs may contain request metadata, but should not include message bodies or OAuth secrets.</p>
<h2>Your choices and contact</h2><p>You can decline authorization or disconnect at any time. For privacy questions or deletion requests, contact <a href="mailto:{contact}">{contact}</a>.</p>
<h2>Security and changes</h2><p>The service uses HTTPS in hosted deployments and encrypts stored Yandex tokens. This policy may be updated as the service changes; the effective date above will be revised when material changes are made.</p>
</main></html>""")

    @app_mcp.custom_route("/terms", methods=["GET"], include_in_schema=False)
    async def terms(_: Request):
        return HTMLResponse("""<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>RAVICOM Mail Terms</title>
<main style="font:16px/1.6 system-ui;max-width:760px;margin:48px auto;padding:0 20px">
<h1>RAVICOM Mail Terms of Service</h1><p>Effective date: 22 October 2026</p>
<p>RAVICOM Mail is an optional tool that connects your own Yandex Mail account to ChatGPT through an authenticated MCP service.</p>
<h2>Acceptable use</h2><p>You may use the service only with a mailbox you control or are authorized to manage. You are responsible for reviewing tool requests and confirming mailbox changes.</p>
<h2>Service limits</h2><p>The service is provided as an evolving product and may be unavailable during maintenance. It does not send mail or permanently delete messages. Cleanup actions move messages to Trash only after an explicit confirmation.</p>
<h2>Third-party services</h2><p>Yandex Mail and ChatGPT are separate services with their own terms, privacy policies, and availability. You must follow their rules when using RAVICOM Mail.</p>
<h2>Changes and contact</h2><p>We may update these terms as the service changes. Material changes will be reflected in the effective date. For support, use the support page or the privacy contact shown there.</p>
</main></html>""")

    @app_mcp.custom_route("/support", methods=["GET"], include_in_schema=False)
    async def support(_: Request):
        contact = html.escape(os.getenv("PRIVACY_CONTACT_EMAIL", ""))
        return HTMLResponse(f"""<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>RAVICOM Mail Support</title>
<main style="font:16px/1.6 system-ui;max-width:760px;margin:48px auto;padding:0 20px">
<h1>RAVICOM Mail Support</h1><p>RAVICOM Mail connects your Yandex Mail account to ChatGPT through MCP.</p>
<h2>Common fixes</h2><ul><li>Keep the hosted service reachable at its HTTPS address.</li><li>Reconnect Yandex Mail if access has expired or the mailbox was disconnected.</li><li>Start with read-only tools such as folder listing and mailbox statistics.</li></ul>
<h2>Contact</h2><p>For connection, privacy, or deletion requests, email <a href="mailto:{contact}">{contact}</a>.</p>
</main></html>""")

    @app_mcp.custom_route("/.well-known/openai-apps-challenge", methods=["GET"], include_in_schema=False)
    async def openai_challenge(_: Request):
        token = os.getenv("OPENAI_APPS_CHALLENGE", "")
        if not token:
            return JSONResponse({"error": "challenge not configured"}, status_code=404)
        return HTMLResponse(token, media_type="text/plain")

    return app_mcp.streamable_http_app()


def main():
    transport = os.getenv("MCP_TRANSPORT", "stdio").strip().lower()
    if transport == "streamable-http":
        import uvicorn
        uvicorn.run(create_http_app(), host=os.getenv("MCP_HOST", "0.0.0.0"),
                    port=int(os.getenv("PORT", os.getenv("MCP_PORT", "8000"))),
                    # OAuth codes arrive in the callback query string. Avoid writing them to access logs.
                    access_log=False)
    else:
        server = _new_mcp(remote=False)
        server.run(transport="stdio")


if __name__ == "__main__":
    main()
