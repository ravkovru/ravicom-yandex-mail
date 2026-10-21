# RAVICOM Mail for Yandex

Experimental local MCP server for Yandex Mail. Uses IMAP over TLS and OAuth XOAUTH2. It does not accept mailbox passwords, send mail, or permanently delete messages. Cleanup moves messages to Trash only after an explicit second call.

## Setup

Requires Python 3.11+ and an IMAP-enabled Yandex mailbox.

1. Create an OAuth application at [oauth.yandex.com](https://oauth.yandex.com/). Select a mail-client application and grant `mail:imap_full` (folder access, reading, flags, and moves). Keep the client secret private.
2. Copy `.env.example` to `.env`; set `YANDEX_CLIENT_ID`, `YANDEX_CLIENT_SECRET`, and `YANDEX_EMAIL` to the application credentials and mailbox address.
3. Run `python -m pip install -e '.[test]'`.
4. Run `python scripts/oauth_device_flow.py`; open the shown Yandex verification page and enter the one-time code. Copy the resulting access token into `YANDEX_ACCESS_TOKEN` in `.env`. The token is only read into process memory by the server; protect `.env` and never commit/share it. Repeat authorization if it expires.
5. Start the stdio MCP server with `ravicom-yandex-mail` (or `python -m ravicom_mail.server` with `PYTHONPATH=src`). In your MCP client configure a local stdio server with that command and the project directory as working directory.

OAuth device authorization availability depends on Yandex application settings/account. If device code flow is unavailable, complete Yandex's supported OAuth authorization flow in the browser and supply its access token through `YANDEX_ACCESS_TOKEN`; the IMAP XOAUTH2 integration is unchanged.

## MCP tools

`list_folders`, `mailbox_stats`, `search_mail`, `read_message`, `mark_read`, `mark_unread`, `move_messages`, `cleanup_preview`, `execute_cleanup`.

Search dates use IMAP format such as `01-Jan-2025`; IDs are folder-scoped IMAP UIDs. Results are capped at 200 and cleanup previews at 500. A preview expires after 15 minutes and can be executed once with exact confirmation `MOVE TO TRASH`. The server never exposes permanent deletion.

## Connect to ChatGPT for a private test

The server supports Streamable HTTP at `/mcp`, protected by a required bearer key. The bearer key protects the tunnel; the Yandex OAuth access token is used only by this server for IMAP XOAUTH2. This is a private development setup, not the production OAuth authorization flow required for a public plugin.

1. Complete the OAuth setup above and install the project: `python -m pip install -e '.[test]'`.
2. Generate a separate MCP key: `openssl rand -hex 32`. Put it in your local `.env` as `MCP_BEARER_TOKEN=...`; do not commit or share the `.env` file.
3. In `.env`, set `MCP_TRANSPORT=streamable-http`. Keep `MCP_HOST=127.0.0.1` and `MCP_PORT=8000`.
4. Start `ravicom-yandex-mail` in a terminal. In a second terminal, start a temporary HTTPS tunnel: `cloudflared tunnel --url http://127.0.0.1:8000`. Keep both processes running. Cloudflare prints a temporary `https://…trycloudflare.com` address.
5. In ChatGPT open **Plugins → Add → Add custom MCP server**, enter `https://…trycloudflare.com/mcp`, select bearer/API-key authentication, and enter the same MCP key. Review the access prompt and connect it. The tunnel URL changes when Cloudflare restarts.
6. In a new chat, select the RAVICOM Mail app and try `List my Yandex Mail folders` or `Show a short overview of my Yandex mailbox`.

The MCP bearer key must stay private: anyone who gets it can use the connected mailbox tools while the server and tunnel are running. Keep access limited to your own ChatGPT account. This development flow is not suitable for sharing or public catalogue submission. A production release needs per-user OAuth 2.1 authorization and a stable HTTPS host.

## Docker

Copy `.env.example` to `.env`, fill local values, then run `docker compose run --rm ravicom-yandex-mail`. Attach stdin/terminal when using it as an stdio MCP server. For HTTP mode, set `MCP_TRANSPORT=streamable-http` and run `docker compose up --build`; port 8000 is published on localhost only. Never copy `.env` into an image.

## Tests

`python -m pip install -e '.[test]'` then `pytest`. Tests use fakes and do not contact a real mailbox.

## Security

This is an experimental local server. The HTTP test mode requires `MCP_BEARER_TOKEN`; it fails closed when the key is absent. Yandex access tokens remain in local `.env` and process memory; restrict `.env` permissions. Do not expose the server without the bearer key. Public use needs per-user OAuth 2.1, a stable HTTPS deployment, and security review.
