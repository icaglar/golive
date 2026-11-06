---
name: mail
description: Sets up an app's e-mail with the sending provider the user chooses - Resend, Postmark, Mailgun, Amazon SES, Brevo or others - (adds the sending domain, writes its SPF/DKIM/return-path records with the DNS provider's tool as DNS-only, verifies, adds DMARC, sends a test), receives info@/dmarc@ through Cloudflare Email Routing, the registrar's forwarding or a mailbox provider, and configures the app (API key or SMTP on port 587, never 465 or 25 where the hosting provider blocks them). Use for the mail_send, mail_inbound and app_config go-live steps, or when the user says "SMTP ayarla", "mail ayarları", "SPF DKIM DMARC", "mail spam'e düşüyor", "info@ adresi kur", "Postmark", "Mailgun", "SES".
---

# Mail: send through the chosen provider, receive per DNS provider

Talk to the user in the language they use. Values from `.claude/golive.yaml` (`mail.*`). How to talk to each provider, its record shapes and SMTP host: `${CLAUDE_PLUGIN_ROOT}/skills/mail/providers.md`. DNS writes use the DNS provider's tool: the Cloudflare MCP when `domain.dns_provider` is `cloudflare`, otherwise the tool in `${CLAUDE_PLUGIN_ROOT}/skills/dns/providers.md`. Always **DNS-only (not proxied)** and always as upserts. Expect a guard prompt on Cloudflare DNS writes. Check the name first and merge SPF instead of adding a second `v=spf1` record.

## 0. Provider

Use `mail.provider`. If it is not set, ask with `AskUserQuestion`: Resend (recommended default: bundled MCP, simple, EU region) / Postmark (strong transactional deliverability) / Amazon SES (cheapest at volume, more setup) / Other (Mailgun, Brevo, ...). Mention once that marketing mail needs consent under the users' law (GDPR/ePrivacy, PECR, CAN-SPAM, CASL, İYS in Turkey; see the `legal` skill) whatever the provider. Record `mail.provider`, and from providers.md the provider's sending subdomain and DKIM selector in `mail.send_subdomain` / `mail.dkim_selector` (the audit uses them). Providers without a sending subdomain (Google Workspace, Brevo, and any other whose records sit on the apex; check the provider's records): set `mail.send_subdomain` to empty so the audit runs with `--no-send-subdomain`.

## A. Sending domain (mail_send)

1. **Add the sending domain** in the provider: with its MCP if bundled or connected (Resend), else its API or CLI with a key the user exported in their own terminal (Postmark, Mailgun, Brevo; SES through `aws sesv2 create-email-identity`), else the user adds it in the dashboard (user step). Choose the region matching `profile.data_residency` where the provider offers one. Reuse the domain if it already exists there.
2. **Get its DNS records** from the provider (domain details), typically SPF and DKIM, plus a return-path / bounce record (MX or CNAME) on a subdomain. Use exactly what the provider returns.
3. **Write them** with the DNS provider's tool, DNS-only. Long DKIM values go in as one TXT record; Cloudflare splits the strings itself. If the provider gives SPF for the apex and the apex already has an SPF record (Email Routing, Google Workspace), merge the `include:` mechanisms into the one record.
4. **Verify** in the provider and poll for up to ~10 minutes. If it stays pending, compare each record with what the provider expects (typo, proxied by mistake, name doubled as `send.<domain>.<domain>`).
5. **DMARC** on `_dmarc.<domain>`, exactly one record, the same for every provider:
   `v=DMARC1; p=none; rua=mailto:dmarc@<domain>; adkim=r; aspf=r`
   `p=none` only reports. After 2-4 weeks of clean reports (only your own senders), move to `p=quarantine` and update `mail.dmarc_policy`.
6. **Test**: send a test mail from `mail.from` to the user's own inbox (provider's MCP/API, or the app once configured). Ask the user to open it and check "Show original" (Gmail): SPF, DKIM and DMARC should all say PASS. If it lands in spam, run the `audit` skill.
7. Provider-specific gates: Amazon SES starts in the sandbox (only verified recipients) until the user requests production access in the AWS console (user step); some providers review new accounts before sending.

Set `steps.mail_send: done` with provider, region and the sending subdomain.

## B. Inbound (mail_inbound)

0. **Existing mailbox?** Read the apex MX first. If it points at a mail provider (Google Workspace, Microsoft 365, Yandex, a hosting company's mailbox), the domain already receives mail: **do not enable Email Routing**, it replaces those MX records and the real mailboxes stop receiving. Instead set `mail.existing_mailbox`, ask the user to create `info@`/`dmarc@` as aliases at that provider (user step), and mark `mail_inbound` as `skipped` with that note.
**Cloudflare DNS**: Email Routing.
1. **Enable Email Routing** on the zone through the Cloudflare MCP (a guard prompt is expected: it replaces the MX records). It adds MX records and an SPF record on the apex (`include:_spf.mx.cloudflare.net`); if the apex already has an SPF record, merge into one.
2. **Destination address**: ask for `mail.forward_to` if it is not set and add it. Cloudflare mails a verification link; **the user must click it** (user step). Wait until it shows as verified.
3. **Rules**: one per entry in `mail.routes` (default `info@` and `dmarc@`) forwarding to the destination. Leave catch-all off unless the user wants it.

**No Cloudflare**: use the registrar's or DNS host's mail forwarding (user step in its panel; Claude gives the exact aliases and destination), or a mailbox provider (Google Workspace, Microsoft 365, Zoho, a hosting mailbox) whose MX records are written with the DNS provider's tool. Set `mail.inbound` to what was used.
4. **Test**: send a mail to `info@<domain>` and confirm it arrives.

Set `steps.mail_inbound: done`.

## C. App settings (app_config)

- **Key or SMTP password**: created by the user in the provider's dashboard with the narrowest scope it offers (sending only, this domain only) and pasted into the server's `/srv/app/.env` (or the k8s secret) by the user, so it never enters the conversation. If they insist that you create it through an MCP or API, say first that the value will pass through this transcript, and suggest rotating it after the setup. Record only where it lives (e.g. `MAIL_API_KEY in /srv/app/.env`) in `secrets.mail`.
- **Env**: the provider's key variable, `MAIL_FROM` (= `mail.from`), and for SMTP `SMTP_HOST`, `SMTP_PORT=587`, `SMTP_USER`, `SMTP_PASSWORD`. Keep a `.env.example` with empty values.
- **HTTP API** (preferred) through the provider's official SDK, or **SMTP** with the host from providers.md on port **587** with STARTTLS. **Outgoing ports 25/465 are blocked or throttled by many hosting providers** (see the "Outgoing mail ports" column in `${CLAUDE_PLUGIN_ROOT}/skills/server/providers.md` for `server_defaults.provider`; check the provider docs): use 587 or the HTTPS API, otherwise the app just times out.
- Bounces and complaints: if the app sends a lot, wire the provider's webhooks so it stops mailing dead addresses.
- Restart the app afterwards: `cd /srv/app && docker compose up -d` (k8s: roll the deployment).

## D. Own mail server (not the default)

Only if the user insists on self-hosting SMTP: request the port 25/465 unblock from the hosting provider's support (user step), set rDNS to the mail hostname (provider CLI or panel; see `skills/server/providers.md`), use a maintained stack (e.g. docker-mailserver or Stalwart), publish SPF/DKIM/DMARC for it and warm the IP up slowly. Explain that transactional deliverability from a fresh IP is usually worse than a provider's.
