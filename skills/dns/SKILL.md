---
name: dns
description: Moves a domain's DNS to Cloudflare (zone, registrar nameservers, wait until active) and manages records per environment - proxied A/AAAA for apex, www, staging and grafana, DNS-only mail records, cleanup of conflicting records, Cloudflare Access for staging and Grafana - or does the same at another DNS provider with lowered TTLs and basic auth. Use for the nameservers and dns_records go-live steps, or when the user says "DNS ayarla", "Cloudflare'e taşı", "nameserver değiştir", "A kaydı ekle", "domaini sunucuya bağla", "cutover".
---

# DNS (Cloudflare by default)

`domain.dns_provider` decides. Without Cloudflare skip the nameservers step and follow the "Without Cloudflare" section below and `${CLAUDE_PLUGIN_ROOT}/skills/dns/providers.md`. Talk to the user in the language they use. Use the Cloudflare MCP (search the API, then execute); the `cf` CLI or `CLOUDFLARE_API_TOKEN` work too. Read values from `.claude/golive.yaml`.

## Nameservers step

1. **Zone**: find it in the user's Cloudflare account (the account per `profile.accounts`); if missing create it (`type: full`, Free plan). Note the two nameservers.
2. **Review imported records, always.** Existing domain: compare with the old provider, especially MX, SPF/DKIM TXT and verification records (missing MX silently breaks mail). Fresh purchase: list registrar parking records; they are deleted in the records step.
3. **DNSSEC (existing domains)**: if a DS record exists at the parent, remove it at the registrar first and wait for its TTL (often a day) before switching, or validating resolvers return SERVFAIL for web and mail. Re-enable DNSSEC on Cloudflare later.
4. **Point the registrar at Cloudflare** per the registrar's row in `${CLAUDE_PLUGIN_ROOT}/skills/domain/registrars.md` (MCP/API with the guard's confirmation, nothing for Cloudflare Registrar, else the user enters the two nameservers).
5. **Wait** until the zone is `active` (minutes to hours; zone status or `audit.py --no-mail --no-web`). Do not continue before.
6. Record `domain.dns_provider: cloudflare`, `steps.nameservers: done`.

## Records step (the cutover), per environment

Runs after `deploy` and `tls` (without Cloudflare: after `deploy`, before `tls`; k8s: see below), so the app already answers behind the proxy: no downtime for an existing site. **Staging first, then prod**; record `steps.dns_records.envs.<env>`. IPs come from `servers.<name>` (`ipv4`, `ipv6` as `<prefix>::1`). A guard confirmation is expected on every Cloudflare record write.

| Name | Type | Value | Proxy |
|---|---|---|---|
| `@` | A, AAAA | `servers.app-prod` IPs | proxied |
| `www` | CNAME | apex | proxied |
| `staging` | A, AAAA | `servers.app-staging` IPs (same-server: app-prod's) | proxied |
| `grafana` | A, AAAA | the monitoring server's IPs (only if `monitoring.where` has a server) | proxied |
| extra app hosts (`api`, ...) | A/AAAA | app-prod IPs | proxied |

Rules: web hosts are proxied (the Origin CA certificate is trusted only through the proxy); mail records (MX, SPF/DKIM/DMARC, `mail.` hosts) are never proxied; one SPF record per name (merge `include:`s); upsert by name+type; show the exact record and get a yes before deleting; TTL auto.

**Staging protection** (`environments.staging.protection`, default `cloudflare-access`): create the **Cloudflare Access application** here for `staging.<domain>` (and `grafana.<domain>`): self-hosted app, policy allowing the e-mail addresses of `profile.accounts.team` plus the owner (one-time PIN login). Create it before the staging record goes live, then verify an unauthenticated `curl -sSI https://staging.<domain>` is redirected to the Access login. Access writes ask for confirmation. If the Access API or plan refuses, give the user the exact click path, or set `protection: basic-auth` (the Caddy staging block needs the basic auth variant: ask the tls skill to render it).

Then, once records point here, apply the Cloudflare SSL settings from the `tls` skill (section 4) if still pending and verify through Cloudflare: `curl -sSI https://<domain>`. Run the `audit` skill: `--no-mail` for the apex, `--host-only` for `staging.<domain>`.

**k8s runtimes**: the cutover happens only after `ci_cd` built the images and `kubectl rollout status` is green for the environment (cluster skill, section D); records point at the load balancer's IP. If the load balancer can be reached directly, remind the user it bypasses Access (cluster skill).

**Replacing a live app** (`profile.replaces_live_app`): the `migrate` step comes first; lower TTLs ahead of time and keep the redirect map ready.

## Without Cloudflare

Records stay at the current DNS provider, written with its tool (providers.md). Differences: Let's Encrypt in Caddy, 80/443 open to everyone, staging behind **basic auth** (no Access), no Email Routing/WAF. Order: `dns_records` before `tls`. If a live site exists, **lower the TTL of the records to be changed to 300 s a day or more before the cutover** (wait out the old TTL), switch, verify, raise the TTL again later. Same record rules (upsert, one SPF, mail never proxied, confirm deletes). Check DNSSEC before changing nameservers. Run `audit.py --dns-provider other`.

## Email Routing and other guarded actions

Enabling Cloudflare Email Routing replaces MX records: the guard asks and you show the before/after MX first. The `mail` skill owns that decision.

## Optional later: DNSSEC

When everything is stable, enable DNSSEC on the zone and add the DS record at the registrar. Never during initial setup; a wrong DS record takes the domain offline.
