---
name: audit
description: Runs deterministic go-live checks against a live domain - nameservers, A/AAAA/www, MX, SPF (one record, no +all), DKIM, DMARC policy and reports, PTR, HTTPS reachability, HTTP→HTTPS redirect, HSTS, security headers, TLS certificate expiry, robots.txt, sitemap, security.txt - and maps every failure to the golive skill that fixes it. Use when the user asks to check, audit or verify a domain or a go-live, or says "domain'i kontrol et", "mail ayarları doğru mu", "SPF DKIM DMARC kontrol", "canlı kontrol listesi".
---

# Audit a go-live

Talk to the user in the language they use.

## Run

Take the domain and mail settings from `.claude/golive.yaml` when it exists (domain.name, mail.send_subdomain, mail.dkim_selector, and the hosts from `servers:`: `servers.app-prod.ipv4/ipv6/rdns`; old files have a single `server:` block, treat it as `servers.app-prod`), otherwise from the user.

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/audit.py" example.com \
  --mail-subdomain <mail.send_subdomain> --dkim-selector <mail.dkim_selector> \
  --server-ip <ipv4> --ptr-host <rdns host>
```

Use `python` if `python3` is missing. Options that matter:

- `--host-only`: for subdomain hosts such as `staging.<domain>` (the `environments.staging.host`, with `servers.app-staging` addresses). It skips the NS and mail checks, which only make sense on the registered domain. Run the apex without it, each staging host with it.
- `--no-send-subdomain` (or `--mail-subdomain ''`): when the mail provider has no sending subdomain (Google Workspace, Brevo, some others per `${CLAUDE_PLUGIN_ROOT}/skills/mail/providers.md`); SPF and DKIM are then checked on the apex, not on `send.<domain>`.

Add `--no-mail` when the project sends no mail, `--dns-provider other` when DNS is not on Cloudflare, `--json` when you need to parse the results. The script needs no packages and resolves DNS over HTTPS, so results do not depend on local resolver caches. Exit code 1 means at least one FAIL.

## Report

Show the table as the script prints it, then a short list of fixes, worst first. Map each FAIL/WARN to its fix:

| Check | Fix with |
|---|---|
| NS, A, AAAA, www | `dns` skill |
| HTTPS, redirect, HSTS, headers, TLS | `tls` skill |
| MX, SPF, DKIM, DMARC, PTR | `mail` skill (PTR: `server` skill, the provider's reverse-DNS setting) |
| robots.txt, sitemap, security.txt | app code; offer to add them |

DNS changes can take minutes to show up (TTL); if a record was just added, say so instead of reporting it as broken, and re-run later.

If `.claude/golive.yaml` exists, set `steps.audit` to `done` when there is no FAIL on the apex and none on the staging hosts (`--host-only`), otherwise leave it `pending` with the failing checks in its note.
