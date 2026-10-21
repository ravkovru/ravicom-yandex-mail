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

## Local Streamable HTTP test

The server supports Streamable HTTP at `/mcp`, protected by a required bearer key. Use this mode with MCP Inspector or another development client. The bearer key protects the local HTTP endpoint; the Yandex OAuth access token is used only by this server for IMAP XOAUTH2.

1. Complete the OAuth setup above and install the project: `python -m pip install -e '.[test]'`.
2. Generate a separate MCP key: `openssl rand -hex 32`. Put it in your local `.env` as `MCP_BEARER_TOKEN=...`; do not commit or share the `.env` file.
3. In `.env`, set `MCP_TRANSPORT=streamable-http`. Keep `MCP_HOST=127.0.0.1` and `MCP_PORT=8000`.
4. Start `ravicom-yandex-mail` in a terminal.
5. In MCP Inspector, select Streamable HTTP, enter `http://127.0.0.1:8000/mcp`, and configure `Authorization: Bearer <your MCP key>` in request headers. Test read tools first.

This development HTTP key is for MCP Inspector only. Do not expose the bearer-protected HTTP endpoint through a tunnel: the documented tunnel client supports a local stdio MCP process directly, which is simpler and avoids exposing an HTTP listener.

## Test in ChatGPT through Secure MCP Tunnel

This keeps the MCP server and Yandex token on your computer. The OpenAI tunnel client makes an outbound connection; no public inbound port is opened. The tunnel client requires a Platform tunnel ID and a runtime API key with Tunnels Read + Use. Creating a tunnel requires Tunnels Read + Manage. Tunnel permissions and ChatGPT custom MCP access are separate.

1. Complete Yandex OAuth setup above and install the package: `python -m pip install -e .`. The `.env` must contain `YANDEX_ACCESS_TOKEN` and `YANDEX_EMAIL`.
2. Sign in to [OpenAI Platform](https://platform.openai.com/settings/organization/tunnels), create a Secure MCP Tunnel, and associate it with the ChatGPT workspace you intend to use. Copy its `tunnel_id`.
3. Download the current `tunnel-client` release from the official [OpenAI tunnel-client repository](https://github.com/openai/tunnel-client). In a terminal, follow its current install instructions and confirm `tunnel-client help quickstart` works.
4. Create a runtime API key with Tunnels Read + Use. In zsh, enter it without putting the secret in shell history:

   ```zsh
   read -s "CONTROL_PLANE_API_KEY?Paste the OpenAI tunnel runtime key: "
   export CONTROL_PLANE_API_KEY
   ```

   Paste the key at the hidden prompt and press Enter. Then run the commands below in the same terminal and keep it open while testing. Do not paste the key into ChatGPT, a command argument, or a tracked file.
5. From the project directory, initialize and validate the tunnel profile. Replace the example ID with your tunnel ID:

   ```sh
   tunnel-client init \
     --sample sample_mcp_stdio_local \
     --profile ravicom-mail \
     --tunnel-id tunnel_REPLACE_WITH_YOUR_ID \
     --mcp-command "./scripts/run-mcp-server.sh"
   tunnel-client doctor --profile ravicom-mail --explain
   tunnel-client run --profile ravicom-mail
   ```

   Keep this process running. The wrapper starts the MCP server from the project directory and removes the OpenAI runtime key from the server process environment. The server reads the Yandex access token from `.env`; it stays on this computer.
6. In ChatGPT Plugins, add a custom MCP server named `RAVICOM Mail`, choose **Tunnel**, select or enter the same tunnel ID, and choose **No authentication** for the private tunnel transport. Review the risk notice and create the plugin. Use the app in a new ChatGPT chat, then test `list_folders` and `mailbox_stats` before any write tools.

ChatGPT must allow custom MCP connections for your account/workspace. OpenAI's current documentation lists full custom MCP for Business and Enterprise/Edu; Pro supports read/fetch only. Plus is not listed as eligible, so the presence of the form alone does not guarantee the server can be used. If the connection is unavailable on your plan, use an eligible workspace to test the full MVP. ChatGPT custom MCP authentication does not accept a customer-provided API key; Secure MCP Tunnel provides the private transport, while Yandex OAuth authorizes this local server to access the mailbox.

## Docker

Copy `.env.example` to `.env`, fill local values, then run `docker compose run --rm ravicom-yandex-mail`. Attach stdin/terminal when using it as an stdio MCP server. For HTTP mode, set `MCP_TRANSPORT=streamable-http` and run `docker compose up --build`; port 8000 is published on localhost only. Never copy `.env` into an image.

## Tests

`python -m pip install -e '.[test]'` then `pytest`. Tests use fakes and do not contact a real mailbox.

## Security

This is an experimental local server. The HTTP test mode requires `MCP_BEARER_TOKEN`; it fails closed when the key is absent. Yandex access tokens remain in local `.env` and process memory; restrict `.env` permissions. Keep the HTTP test mode bound to localhost. ChatGPT private testing can use Secure MCP Tunnel with this server's stdio transport. A public connection for other users needs per-user OAuth 2.1, a stable HTTPS deployment, and security review.
