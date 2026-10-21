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

## Docker

Copy `.env.example` to `.env`, fill local values, then run `docker compose run --rm ravicom-yandex-mail`. Attach stdin/terminal when using it as an stdio MCP server. Never copy `.env` into an image.

## Tests

`python -m pip install -e '.[test]'` then `pytest`. Tests use fakes and do not contact a real mailbox.

## Security

This is an experimental local server without token persistence or remote HTTP access. Environment tokens are bearer credentials; restrict `.env` permissions. Do not expose the stdio process over an unauthenticated network.
