# Public deployment runbook

This service is ready for a single-instance HTTPS deployment. It is not a public service until a domain, persistent disk, Yandex OAuth callback, and secrets are configured.

## Required production values

- `DOMAIN`: the final HTTPS hostname, for example `mail.your-domain.example`.
- `YANDEX_CLIENT_ID` and `YANDEX_CLIENT_SECRET`: the Yandex OAuth application credentials.
- `TOKEN_ENCRYPTION_KEY`: a new Fernet key generated for this deployment.
- `PRIVACY_CONTACT_EMAIL`: a monitored public support/privacy address.
- `OPENAI_APPS_CHALLENGE`: only when the OpenAI submission portal provides a domain challenge.

Register `https://DOMAIN/oauth/yandex/callback` in Yandex OAuth before starting the service. Point DNS for `DOMAIN` to the host running Caddy. Keep `/data` on persistent storage and run one application replica while using SQLite.

## First deployment

1. Copy `deploy/.env.production.example` to `.env.production` outside Git.
2. Fill the values above and set `DOMAIN`.
3. Start with `docker compose -f docker-compose.production.yml up -d --build`.
4. Verify `/health`, `/privacy`, `/terms`, `/support`, and the OAuth discovery endpoints.
5. Use `plugin.json.example` as the submission manifest after replacing `YOUR_DOMAIN` and adding the final app identity assets.

Do not put Yandex secrets, access tokens, Fernet keys, or OpenAI runtime keys in Git, Docker images, plugin manifests, or support tickets.
