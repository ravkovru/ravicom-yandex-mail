# RAVICOM Mail for Yandex

RAVICOM Mail connects ChatGPT to Yandex Mail through MCP, IMAP over TLS, and OAuth/XOAUTH2. It never accepts mailbox passwords, sends mail, or permanently deletes messages. Cleanup first previews candidates and only moves them to Trash after an explicit second call.

The repository supports local single-user development and a hosted per-user OAuth mode. Hosted mode gives every ChatGPT user their own Yandex authorization; Yandex tokens are encrypted at rest and cleanup confirmations are isolated by account. A public listing also requires an HTTPS domain, privacy policy, verified publisher identity, and OpenAI app review; deployment and listing are not automatic.

## Setup

Requires Python 3.11+ and an IMAP-enabled Yandex mailbox.

1. Create an OAuth application at [oauth.yandex.com](https://oauth.yandex.com/). Select a mail-client application and grant `mail:imap_full` (folder access, reading, flags, and moves). Keep the client secret private.
2. Copy `.env.example` to `.env`; set `YANDEX_CLIENT_ID`, `YANDEX_CLIENT_SECRET`, and `YANDEX_EMAIL` to the application credentials and mailbox address.
3. Run `python -m pip install -e '.[test]'`.
4. Run `python scripts/oauth_device_flow.py`; open the shown Yandex verification page and enter the one-time code. Copy the resulting access token into `YANDEX_ACCESS_TOKEN` in `.env`. The token is only read into process memory by the server; protect `.env` and never commit/share it. Repeat authorization if it expires.
5. Start the stdio MCP server with `ravicom-yandex-mail` (or `python -m ravicom_mail.server` with `PYTHONPATH=src`). In your MCP client configure a local stdio server with that command and the project directory as working directory.

OAuth device authorization availability depends on Yandex application settings/account. If device code flow is unavailable, complete Yandex's supported OAuth authorization flow in the browser and supply its access token through `YANDEX_ACCESS_TOKEN`; the IMAP XOAUTH2 integration is unchanged.

## MCP tools

`list_folders`, `create_folder`, `mailbox_stats`, `search_mail`, `read_message`, `mark_read`, `mark_unread`, `move_messages`, `cleanup_preview`, `execute_cleanup`.

Search dates use IMAP format such as `01-Jan-2025`; IDs are folder-scoped IMAP UIDs. Results are capped at 200 and cleanup previews at 500. A preview expires after 15 minutes and can be executed once with exact confirmation `MOVE TO TRASH`. The server never exposes permanent deletion.

## Hosted public MCP deployment

The repository includes the public product runbook in [`deploy/README.md`](deploy/README.md), a portable MCP server manifest in [`mcp.json`](mcp.json), and a public listing template in [`plugin.json.example`](plugin.json.example). Replace `mail.ravicom.ru` only after the final HTTPS hostname is selected.

Hosted mode is intended for a stable HTTPS deployment with a persistent writable volume mounted at `/data`. Each user authorizes their own Yandex mailbox through OAuth 2.1; Yandex tokens are encrypted in the database. Keep one service instance while using SQLite. Do not scale horizontally or remove the persistent disk without first moving to a shared database adapter.

### Public deployment with Docker Compose

Requirements: a Linux server with Docker Compose, a domain whose DNS A/AAAA records point to the server, and inbound ports 80 and 443 open. Caddy obtains and renews HTTPS certificates automatically.

1. Create a Yandex OAuth application as described in Setup. For its web platform, add `https://mail.ravicom.ru/oauth/yandex/callback` to the application's Redirect URI list. Yandex only accepts redirect URLs registered in the app settings.
2. On the server, copy `deploy/.env.production.example` to `.env.production`. Set `DOMAIN`, `PRIVACY_CONTACT_EMAIL`, `YANDEX_CLIENT_ID`, and `YANDEX_CLIENT_SECRET`. Generate the Fernet key locally with `python3 -c 'import base64,os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())'` and set `TOKEN_ENCRYPTION_KEY`. Keep `.env.production` private; Git ignores it.
3. Start the service with `docker compose --env-file .env.production -f docker-compose.production.yml up -d --build`.
4. Confirm `https://mail.ravicom.ru/health` and `https://mail.ravicom.ru/privacy` load. The public MCP endpoint is `https://mail.ravicom.ru/mcp`.
5. Add that HTTPS URL as a custom remote MCP server in an eligible ChatGPT workspace. Choose OAuth, complete Yandex authorization, then test `list_folders` and `mailbox_stats` before any write tool.

The application container runs as a non-root user, has a health check, and stores its database on a persistent named volume. Caddy terminates TLS and proxies to the application over the private Docker network. Back up the database volume and Fernet key together; treat both as sensitive.

### Hosted environment variables

For a different Docker host, configure these values in its secret manager, never in Git:

- `PUBLIC_BASE_URL=https://<your-domain>`
- `DATABASE_URL=sqlite:////data/ravicom-mail.sqlite3` (single service instance with persistent volume)
- `TOKEN_ENCRYPTION_KEY=<Fernet key>`; generate with `python3 -c 'import base64,os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())'`
- `PRIVACY_CONTACT_EMAIL=<public privacy contact address>`; required at startup and shown on `/privacy`
- `YANDEX_CLIENT_ID` and `YANDEX_CLIENT_SECRET`
- `MCP_TRANSPORT=streamable-http`, `MCP_HOST=0.0.0.0`, `MCP_PORT=8000`

The service honors the hosting platform's `PORT` variable and Render's `RENDER_EXTERNAL_URL`. `PUBLIC_BASE_URL` must be the stable HTTPS origin used by the Yandex OAuth callback. The server exposes MCP at `/mcp`, health at `/health`, and OAuth metadata under `/.well-known/`. Keep `/data` persistent. SQLite is suitable for one replica; multi-replica hosting needs a shared transactional database and store adapter.

For local hosted-mode checks, use `docker compose up --build` after setting the environment values in `.env`. The local Compose file binds to localhost and is not reachable by other users. Secure MCP Tunnel is for private testing; public access needs a stable HTTPS endpoint.

After deployment, test `/health`, `/privacy`, OAuth discovery, account connection, token refresh, revocation, and per-user isolation. Custom MCP connections are available in eligible ChatGPT Business and Enterprise/Edu workspaces; availability also depends on workspace settings. Public app directory submission and review are separate from deployment and are not automatic.

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

For hosted OAuth mode, configure the deployment values above and run `docker compose up --build`; port 8000 is published on localhost only and the database persists in the named Docker volume. Never copy `.env` into an image. For local stdio mode, run `docker compose run --rm ravicom-yandex-mail` with local Yandex token settings.

## Tests

`python -m pip install -e '.[test]'` then `pytest`. Tests use fakes and do not contact a real mailbox.

## Security

The hosted server stores only encrypted Yandex tokens, uses OAuth state/PKCE on the ChatGPT authorization flow, and scopes every connected mailbox to its individual OAuth subject. Mutating mailbox tools require `mail:manage`; all cleanup previews are one-use, expire after 15 minutes, and are scoped to the account that created them. The server intentionally has no permanent-delete or send-mail tool. Before public release, configure a verified domain, rotate the OAuth secret, publish a privacy policy, conduct a security review, and complete OpenAI app review.
