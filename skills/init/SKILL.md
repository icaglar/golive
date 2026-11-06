---
name: init
description: Starts the go-live process for the current app - checks the tools for the providers you pick, asks a few forms of questions (domain, providers, mail, legal, then data residency, budget and availability, replacing a live app, app shape, accounts, staging layout, GitHub) and creates the .claude/golive.yaml state file with the whole step chain. Use when the user wants to take an app to production, put it live, buy a domain and set up the server and mail, or says "canlıya alalım", "yayına alalım", "golive başlat", "domain alıp sunucuyu kuralım". If .claude/golive.yaml already exists, show its status instead of recreating it.
---

# Start a go-live

Talk to the user in the language they use. The state file is `.claude/golive.yaml` at the project root; the template is `${CLAUDE_PLUGIN_ROOT}/templates/golive.yaml`.

## 1. Existing state?

If `.claude/golive.yaml` exists, do not overwrite it. Show a short status table (step, status, owner, note) and point to `/golive:next`. Stop.

## 2. Look at the project

Without asking, find out what you can: stack (`package.json` with svelte/next/vite, `pyproject.toml` or `requirements.txt` with fastapi/django, `docker-compose.yml`/`compose.yaml`, `Dockerfile`), the ports the services listen on, whether the app sends mail (smtp/resend/sendgrid in code or `.env.example`), whether it sets cookies beyond a session cookie or loads analytics, and what hints at the app shape (upload folders or S3 code, worker/queue/cron services, websocket or SSE code).

## 3. Ask, form 1: providers and legal

Use `AskUserQuestion`: at most four questions per call (the tool's limit), best guess first and marked "(Recommended)". The providers named are defaults, not requirements.

1. **Domain and registrar**: already owned (where?) or to be bought, and at which registrar: Porkbun (default) / Namecheap / Cloudflare Registrar / other (GoDaddy, a local registrar, ...: "Other" lets them type it). Country-code TLDs with local rules (e.g. `.com.tr`, `.eu`, `.us`) may need a local registrar, which becomes a user step. See `${CLAUDE_PLUGIN_ROOT}/skills/domain/registrars.md`.
2. **Server and DNS**: new server at Hetzner Cloud (default) / another cloud (DigitalOcean, Vultr, Linode, AWS Lightsail, Scaleway: "Other") / an existing server or VPS (IP); and DNS on Cloudflare (recommended: proxy, Origin CA, Access, Email Routing, WAF) or at the current DNS provider (see `${CLAUDE_PLUGIN_ROOT}/skills/server/providers.md` and `${CLAUDE_PLUGIN_ROOT}/skills/dns/providers.md`).
3. **Mail**: sending provider Resend (default) / Postmark / Mailgun / Amazon SES / Brevo / no mail (see `${CLAUDE_PLUGIN_ROOT}/skills/mail/providers.md`); receiving through Cloudflare Email Routing unless the domain keeps an existing mailbox (Google Workspace etc.).
4. **Legal scope**: where the company is and where the users are (EU/EEA, UK, US, Canada, Brazil, Turkey, other), and whether the app sends marketing e-mail/SMS or sells online. The `legal` skill turns this into the right checklist. Plugin defaults (empty if the user set none): company country `${user_config.default_company_country}`, user regions `${user_config.default_user_regions}`. If set, offer them as the first, "(Recommended)" answer; the project can still choose differently.

## 4. Ask, form 2: the profile

A second `AskUserQuestion` call (max four questions) for what shapes the infrastructure:

1. **Data residency**: where must the data stay? EU / UK / US / Turkey / no requirement / other region. Drives the provider region for servers, mail, backups, Grafana Cloud and error tracking, and the transfer notes in `legal`. Suggest the answer from the legal scope (EU users: EU).
2. **Budget and availability**: minimal (one small server per environment, cheapest) / balanced (recommended: separate staging, dedicated database without replica, small monitoring server) / high-availability (database replica, monitoring server, optionally HA k3s). Ask in a follow-up line how much data loss (RPO, e.g. "1 h") and downtime (RTO, e.g. "4 h") is acceptable.
3. **Replacing a live app?** No / yes (existing data, users and URLs). Yes turns on the `migrate` step.
4. **Staging layout**: separate server (recommended with balanced and high-availability) / same server as prod / prod only.

Then a third call, also max four questions:

1. **App shape** (multi-select): user uploads or persistent files / background workers or cron / websockets or SSE / customer custom domains. Pre-select from step 2.
2. **Canonical host**: apex (`example.com`, `www` redirects to it) or `www`.
3. **Accounts**: company or personal accounts for cloud, Cloudflare and the registrar; who is billed; which team members need access to staging, Grafana and GitHub; is there a second admin for recovery.
4. **GitHub**: personal account or organization; plan (free / Pro / Team / Enterprise). The plan decides which branch protection and required-reviewer features exist.

If the user answers "I don't know" to a question, take the recommended default and write it down.

## 5. Defaults derived from the budget

These are defaults the user can override; say so, and record the result in `environments.layout`, `profile.budget` and the later steps' notes.

| Budget | Staging | Database | Monitoring |
|---|---|---|---|
| minimal | prod-only or same-server | container on the app server, backups to object storage | no monitoring server: Grafana Cloud free tier or an uptime monitor only |
| balanced | separate server (staging smaller) | dedicated database server, no replica | small monitoring server |
| high-availability | separate server | dedicated database with a streaming replica | monitoring server; k3s with 3 masters is an option |

Follow the explicit staging layout answer over the budget default. The `environments` step turns the layout into `servers:` entries.

## 6. Check the tools, only for what was chosen

Run these and report what is missing; do not fix anything yet.

- The server provider's CLI and credentials, per `${CLAUDE_PLUGIN_ROOT}/skills/server/providers.md` (Hetzner: `hcloud version` and `hcloud context active`; missing CLI: `brew install hcloud` on macOS, otherwise https://github.com/hetznercloud/cli/releases; no context: the user creates an API token in the provider's console with write access and runs `hcloud context create <project>` in their own terminal, because it prompts for the token). Skip this for an existing VPS (SSH only).
- MCP servers, only for the providers chosen: the DNS provider (`cloudflare` if DNS is there), the registrar's (`porkbun` or `namecheap`), the mail provider's (`resend`). Check that the needed ones have tools available. If not, the user signs in to each once (OAuth): in Claude Code with `/mcp`; in claude.ai, the desktop app or Cowork under Customize → Plugins → golive → Connectors.
- GitHub: the `github` MCP needs the plugin option `github_token` (a fine-grained token, see the option's description; `/config` changes it). Also check `gh auth status`. Either one is enough for the repo and CI parts; the deploy key needs `gh` or a manual step.
- `ssh -V` and a public key in `~/.ssh/` (`id_ed25519.pub` preferred).

Never ask for a token in chat.

## 7. Write the state file

Copy the template to `.claude/golive.yaml` and fill in what you know: project name, domain, stack, upstream ports, mail settings, `legal` flags, the whole `profile:` block from forms 2 and 3, `environments.layout`, `server_defaults.provider`, date. Mark steps that do not apply as `skipped` with a one-line note (for example `domain: skipped, note: already owned at Porkbun`; `migrate: skipped` unless `profile.replaces_live_app`). For a `.tr` domain set `domain.registrar: local-tr` and the `domain` and `nameservers` steps to `owner: user`.

Record where each secret lives in `secrets:`; never a value. The guard hook refuses to write tokens into this file.

## 8. Show the plan

Show the status board first (the `status` skill), so the user sees the whole flow with every step still pending. Then print the chain as a numbered list in this order, each with its status and whether it costs money (domain ≈ yearly registrar price; servers, volumes, load balancers, object storage and paid services are monthly; billable steps add to the cost line on the status board):

1. domain, 2. nameservers, 3. environments, 4. server (per environment; compose), 5. cluster (k8s runtimes instead of server and deploy), 6. database, 7. deploy (per environment; compose), 8. tls, 9. migrate (only when replacing a live app), 10. dns_records (the web cutover), 11. ci_cd, 12. mail_send, 13. mail_inbound, 14. app_config, 15. ops, 16. monitoring, 17. legal, 18. launch, 19. audit.

Mention that the order shifts a little without Cloudflare or on k8s (the `next` skill owns the rules). Then say that `/golive:next` runs the next step and asks before anything that costs money.
