# golive

A Claude Code plugin that takes an app from a repo to production without the chores, with the providers you choose: domain, DNS, servers, database, TLS, CI/CD, mail, monitoring, ops basics and a legal checklist for your users' jurisdictions. Every step is tracked in `.claude/golive.yaml`, and nothing that costs money or deletes infrastructure runs without your confirmation.

> **Status:** 1.0.0. The scripts are covered by tests (guard, audit, status board), but the full chain has not yet been run end to end against real provider accounts. Provider CLI flags change over time; the skills check `--help` before using them. Issues and pull requests are welcome.

## Install

In Claude Code:

```
/plugin marketplace add icaglar/golive
/plugin install golive@golive
```

On Claude Code 2.1.275 or later this also works in one step: `/plugin install golive --marketplace icaglar/golive`. In claude.ai, the desktop app or Cowork: Customize → Plugins → Add → Add marketplace → `icaglar/golive`.

## The chain

Providers named below are defaults (Hetzner, Cloudflare, Porkbun, Resend); each is a choice made in `/golive:init` and read back from the state file.

| # | Step | What happens | Cost |
|---|---|---|---|
| 1 | domain | Buy the domain at the registrar you choose (or note that you own it) | yearly registrar price |
| 2 | nameservers | Move DNS to Cloudflare (default), or keep it where it is and use Let's Encrypt | free |
| 3 | environments | Layout (separate servers, same server, prod only), runtime (Compose, k3s, managed Kubernetes, k3sup), staging protection | – |
| 4 | server | Compose: create and harden one server per environment (any listed cloud, or an existing VPS through `bootstrap.sh`) | monthly server price |
| 4' | cluster | k8s instead of server and deploy: cluster, ingress, secrets, Kustomize overlays, Flux | nodes + load balancer |
| 5 | database | PostgreSQL or MySQL: container, dedicated server, replica or operator; encrypted point-in-time backups, offsite copy, restore drill | DB servers, volumes, object storage |
| 6 | deploy | Compose: repo check, deploy key, clone, `.env` with server-generated secrets, pull unit | – |
| 7 | tls | Origin CA certificate (Cloudflare) or Let's Encrypt | free |
| 8 | migrate | Only when replacing a live app ("Migration"): inventory, data import, uploads, 301 redirect map, rehearsal, rollback | – |
| 9 | dns_records | The web cutover, per environment (staging behind Cloudflare Access or basic auth) | free |
| 10 | ci_cd | Tests, image scan, GHCR images, release workflow, branch protection, Dependabot | free tier minutes |
| 11-12 | mail_send, mail_inbound | Sending provider with SPF/DKIM/DMARC; inbound forwarding unless a mailbox exists | provider's plan |
| 13 | app_config | App mail settings, from the server | – |
| 14 | ops | Hardening extras, rebuild notes (`infra/rebuild.md`), backups of uploads and `.env` | depends |
| 15 | monitoring | Prometheus, Grafana, Alertmanager (own server, kube-prometheus-stack or Grafana Cloud), dead-man's switch | small server or free tier |
| 16 | legal | Privacy notice, cookies, processors and transfers (from your data residency), terms, checklist | lawyer review |
| 17 | launch | Readiness: rebuild and restore drills, rollback, alerts, branch protection, costs | – |
| 18 | audit | `scripts/audit.py` on the domain and the staging hosts | free |

Order rules: with Cloudflare, `tls` comes before the cutover; without it, `dns_records` comes first because Let's Encrypt needs the records. On k8s, `ci_cd` comes before the cutover so images exist, and `server` and `deploy` are skipped. The cutover always waits until the app runs on the new infrastructure, so a domain with a live site has no downtime.

## Usage

- `/golive:init`: asks about providers, legal scope, data residency, budget and availability, replacing a live app, app shape, accounts and staging layout, checks only the tools you need, writes `.claude/golive.yaml`.
- `/golive:next`: runs the next pending step and updates the state file. Say "devam" to keep going.
- `/golive:audit example.com`: deterministic checks (NS, A/AAAA, MX, SPF, DKIM, DMARC, PTR, HTTPS redirect, HSTS, headers, certificate expiry). Exits 1 on any failure, so it also works in CI.
- Each step is also a skill you can call directly: `domain`, `dns`, `environments`, `server`, `deploy`, `cluster`, `database`, `tls`, `workflows`, `migrate`, `mail`, `ops`, `monitoring`, `legal`, `launch`.
- `/golive:status`: the status board: progress bar, steps by phase (✅ done, 🔄 in progress, ⏳ pending, ⛔ waiting for you, ➖ skipped), the next step and what is missing. The header carries a running monthly cost total from `costs:`, which every billable step appends to; it is a tally of what golive created, not an invoice. It is also shown automatically after every step (a hook refreshes it whenever `.claude/golive.yaml` changes) and written as a visual page to `.claude/golive-status.html`. Set the plugin option `language` to `tr` for Turkish.
- Plugin options `default_company_country` and `default_user_regions` (e.g. `TR` and `tr, eu`) pre-fill the legal questions for new projects; each project still decides for itself and stores its answer in `.claude/golive.yaml`.
- `/golive:release`: shows what staging runs and what changed since production, asks you, then releases it (or rolls back). Production never deploys without your yes; on private repos GitHub's own required-reviewer gate needs GitHub Enterprise, so golive asks in the conversation instead.

## Release model

Production changes only through `/golive:release`. Merging to `main` builds and tests; `release.yml` then moves the git tag `golive-staging` or `golive-prod` to the released commit and retags the images (k8s: it pins `sha-<commit>` in the overlay). Each server runs a pull timer that checks out the tag for its own environment (`golive-<env>`, never `main`), runs migrations and restarts the stack, so a server follows its tag and nothing else. Branch protection on `main` with the required `ci` check is part of the launch checklist.

## Setup

1. Install the plugin, then run `/golive:init`: it asks which providers you use and checks only those. Sign in once (OAuth) to the connectors of the providers you chose: `/mcp` in Claude Code, or Customize → Plugins → golive → Connectors in claude.ai, the desktop app and Cowork. Providers are choices: Cloudflare, Porkbun and Resend are defaults, and any registrar, DNS provider, cloud and mail provider works through its API, CLI or panel; see `skills/domain/registrars.md`, `skills/dns/providers.md`, `skills/server/providers.md` and `skills/mail/providers.md`. Leave unused connectors off.
2. **GitHub**: the bundled `github` MCP (GitHub's remote server, `repos` and `actions` toolsets) needs a fine-grained token, entered as the plugin option `github_token` (stored in secure storage, never in settings). Permissions: Metadata read, Contents read, Actions read and write; Administration read and write only if golive should create repos or set branch protection. The `gh` CLI stays: it adds the server's deploy key and is the fallback for CI tasks. If you leave the token empty, turn the `github` server off in `/mcp`.
3. The server provider's CLI and credentials, when you use one (Hetzner: `brew install hcloud`, an API token with Read & Write from the console, then `hcloud context create <project>` in your own terminal). Nothing needed for an existing VPS beyond SSH.
4. An SSH key (`~/.ssh/id_ed25519.pub`).
5. Optional, with Porkbun: top up account credit before buying a domain; Porkbun purchases are paid from credit, not a card.

## Safety

`hooks/hooks.json` runs `scripts/guard.py` before every Bash, Write/Edit and MCP call:

- **Asks** before: domain purchases, renewals and transfers; billable resources on any listed cloud (servers, volumes, load balancers, managed databases and Kubernetes, buckets); every delete, rebuild, reset or firewall replacement; DNS record deletions, nameserver changes and live Cloudflare record writes (the cutover) or enabling Email Routing; helm installs and upgrades, `kubectl delete` of database clusters or prod paths, `flux uninstall`, `terraform apply/destroy`; destructive data commands (`DROP`, `TRUNCATE`, `docker compose down -v`, volume removal, deleting data directories, backup pruning, replica promotion); GitHub deletions, including `gh api` DELETE; anything that releases to production outside `/golive:release` (workflow dispatches for prod, `:prod` image tags, moving the `golive-prod` tag, edits of `overlays/prod` through the GitHub MCP); delete and create tools of unknown MCP servers. Dry runs pass without a prompt. Steps that run these tell you a confirmation prompt is expected.
- **Refuses** to write API keys, tokens (GitHub, Cloudflare, AWS, Telegram and others), connection strings with passwords or private keys into `golive.yaml`, also through shell edits. The state file records only where a secret lives.
- Turn the prompts off with the plugin option `guard: false`, or everything with `GOLIVE_GUARD=0`.

Tokens are never asked for in chat: the server provider uses its CLI context, the MCP servers use OAuth, database and backup passwords are generated on the server, and you paste the app's mail API key into the server's `.env` yourself.

## Things it knows so you don't have to

- Production only changes when you say yes: servers follow git tags that only the release workflow moves.
- The status board adds up the monthly cost of everything golive created.
- Some clouds (new Hetzner Cloud accounts, for one) block outgoing ports 25 and 465: the app sends through the mail provider's API or SMTP on 587.
- Docker-published ports bypass ufw; the provider firewall allows 80/443 only from Cloudflare's IP ranges (refreshed weekly) and private-network services stay on the private range.
- One SPF record per name: Cloudflare Email Routing (apex) and a sending subdomain do not collide, and existing SPF records are merged, not duplicated.
- Switching nameservers on an existing domain without copying MX records breaks mail, and a leftover DNSSEC DS record takes the whole domain offline: the dns skill checks both first.
- Cloudflare Email Routing replaces existing MX records, so it is skipped when the domain already has a mailbox provider.
- Providers such as Hetzner report IPv6 as a /64; the server answers on `::1`, which is what goes into AAAA records.
- SSH commands use `IdentitiesOnly`, so an agent full of keys does not trip fail2ban on the new server.
- Country-code TLDs with eligibility rules (`.com.tr`, `.eu`, `.us`, ...) are flagged before purchase.

## Tests

```bash
python3 tests/test_guard.py
python3 tests/test_audit.py
python3 tests/test_status.py
```

## Privacy

The plugin itself collects nothing. It connects to third-party services you sign in to: Cloudflare (`mcp.cloudflare.com`), Porkbun (`mcp.porkbun.com`) and Namecheap (`mcp.namecheap.com`) if you use them, Resend (`mcp.resend.com`) if you use it, GitHub (`api.githubcopilot.com/mcp`) and your server provider's API through its CLI; their privacy policies apply. `audit.py` resolves DNS through Cloudflare's and Google's public DNS-over-HTTPS resolvers, and `firewall_rules.py` downloads Cloudflare's published IP ranges.

## License

MIT

## Türkçe özet

Uygulama olgunlaşınca yapılan angarya işleri (domain, DNS, sunucu, veritabanı, SSL, mail, CI/CD, izleme, eski sistemden taşıma, yasal kontrol listesi) adım adım yapar; para harcayan ve silen her işlemde onay ister. Türkiye için KVKK, İYS ve ETBİS `legal` skill'inin bir modülü olarak gelir. Durum panosu için plugin ayarında `language: tr` seçin.
