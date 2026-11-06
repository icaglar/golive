---
name: tls
description: Sets up HTTPS per environment (staging first, then prod) - behind Cloudflare with an Origin CA certificate whose private key never leaves the server, or without Cloudflare with Caddy and Let's Encrypt - Caddy as reverse proxy in the app's docker compose with security headers, real client IP, validated config, then Cloudflare SSL mode Full (strict), Always Use HTTPS, minimum TLS 1.2 and optional Authenticated Origin Pulls. Use for the tls go-live step, or when the user says "SSL kur", "HTTPS ayarla", "sertifika", "Caddy kur", "reverse proxy", "Cloudflare SSL strict".
---

# TLS

Talk to the user in the language they use. Values from `.claude/golive.yaml`. Run per app server, **staging first, then prod**, and record `steps.tls.envs.<env>`. Server commands: `ssh -i <key> -o IdentitiesOnly=yes -p <ssh_port> <deploy>@<ipv4> '…'` with the server from `servers.<name>`. On k8s the `cluster` skill did TLS; skip this skill.

Order (Cloudflare): runs after `deploy` and before the `dns_records` cutover; origin certificate and Caddy first, Full (strict) last (otherwise visitors get 526). Without Cloudflare `dns_records` runs first (Let's Encrypt needs the records), see section 5.

## 1. Caddyfile (local, in the app repo)

Render `${CLAUDE_PLUGIN_ROOT}/templates/Caddyfile` (Cloudflare) or `Caddyfile.letsencrypt` to `Caddyfile` at the repo root:

- `__DOMAIN__` = `domain.name`; `__CANONICAL_HOST__` = apex or `www.<domain>` per `profile.app_shape.canonical_host`; `__ALT_HOST__` = the other one (it redirects to canonical). Let's Encrypt also `__ACME_EMAIL__`, `__STAGING_USER__`, `__STAGING_PASSWORD_HASH__` (hash from `caddy hash-password` run on the server; the password is generated there and the user reads it from the server, it never appears in chat).
- **Keep only the blocks of the server's environment**: the staging server keeps the `staging.<domain>` block and drops the canonical/alt blocks; the prod server the reverse; same-server layout keeps both. Staging is never indexed (the block sets `X-Robots-Tag`). Staging with `protection: basic-auth` on Cloudflare: take the `basic_auth` lines of the staging block in `Caddyfile.letsencrypt` (hash from `caddy hash-password` on the server).
- Upstreams from `app.upstreams` (service:port); extra hosts from `app.hosts` (also for `app_shape.custom_domains`); drop the `/api` block without a separate API; uncomment the websocket and upload blocks when `app_shape` says so.
- Merge the `caddy` service and volumes from `templates/compose.caddy.yaml` into the compose file; replace `__PRIVATE_IP__` (the server's `private_ip`; metrics on 9180 are published on the private IP only). Caddy is the only service with `ports:`. Commit and push after the user agrees; the change reaches the server through the release (`golive-<env>` tag, pull unit). Before the first release the tag does not exist: check out the agreed commit by hand (`git fetch --tags origin && git checkout --detach <sha>`).

## 2. Origin certificate (Cloudflare)

Key and CSR on the server, key never copied:

```bash
ssh … 'mkdir -p /srv/app/certs && cd /srv/app/certs && openssl req -new -newkey ec -pkeyopt ec_paramgen_curve:prime256v1 -nodes \
  -keyout origin-key.pem -out origin.csr -subj "/CN=<domain>" && chmod 600 origin-key.pem && cat origin.csr'
```

With the Cloudflare MCP create an Origin CA certificate from the CSR: hostnames `<domain>` and `*.<domain>` (the wildcard covers staging and grafana, so create it once and place the same pair on every server, generating the key on the first server and copying certificate **and key** between servers over SSH only if the user agrees; otherwise one CSR per server), `origin-ecc`, 5475 days. Write the certificate (public) to `/srv/app/certs/origin.pem`. If the API refuses, the user creates it in the dashboard (SSL/TLS -> Origin Server -> "Use my private key and CSR"); never let the dashboard generate the key. Record the expiry in the step note.

## 3. Start Caddy, validate before reload

```bash
ssh … 'cd /srv/app && \
  docker compose run --rm caddy caddy validate --config /etc/caddy/Caddyfile && \
  docker compose up -d caddy'
```

`caddy validate` is mandatory before every reload or restart. Caddy serves the origin certificate and logs the real client IP (trusted_proxies + `CF-Connecting-IP`). The firewall lets only Cloudflare reach 80/443, so the real test happens after the cutover. After the weekly range alert (`CloudflareRangesChanged`), refresh the `trusted_proxies` list from `firewall_rules.py --format json-ranges`, validate, reload.

## 4. Cloudflare settings

Through the Cloudflare MCP, on the zone: SSL/TLS mode **Full (strict)** (switch off Automatic SSL/TLS first), Always Use HTTPS on, minimum TLS 1.2, Automatic HTTPS Rewrites on. For a new domain apply now; if the domain still serves a live site elsewhere, leave them for `dns_records` (zone-wide settings could break the old origin) and note which case applies. Zone setting writes ask for confirmation.

**Optional: Authenticated Origin Pulls** (only Cloudflare's client certificate may connect): download Cloudflare's origin-pull CA to `certs/cloudflare-origin-pull-ca.pem`, enable it in Cloudflare (SSL/TLS -> Origin Server), swap the `tls` line in the Caddyfile for the commented block, `caddy validate`, reload; verify the site still answers through Cloudflare (check the Cloudflare and Caddy docs for your versions). Offer it as hardening, not a default.

## 5. Without Cloudflare (`domain.dns_provider` not cloudflare)

No origin certificate, no section 4. Use `Caddyfile.letsencrypt`: Caddy gets and renews Let's Encrypt certificates. Open 80/443 to everyone (`firewall_rules.py --public` or the provider firewall). The A/AAAA records must already point at the server, so `dns_records` runs **before** this step. Staging is protected by basic auth in its block (no Cloudflare Access). Then `validate` and start as in section 3; Caddy needs a minute to obtain certificates (`docker compose logs caddy`).

## 6. Check (after the cutover)

`curl -sSI https://<domain>` returns the app with `strict-transport-security`; `http://` redirects; the `audit` skill (`--no-mail`, and `--host-only` for `staging.<domain>`) passes. HSTS starts at one year without `includeSubDomains`/`preload`; add those only when every subdomain is HTTPS.

Set `steps.tls.envs.<env>: done` once Caddy runs with the certificate (settings applied or deferred to `dns_records`, noted).
