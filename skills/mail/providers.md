# Sending providers: how golive works with each

`mail.provider` in `.claude/golive.yaml`; Resend is only the default. For every provider: use **exactly the DNS records the provider returns** (the examples below are shapes, not values), write them DNS-only with the DNS provider's tool (Cloudflare MCP, or `skills/dns/providers.md`), merge SPF instead of adding a second record on the same name, verify in the provider, then DMARC and a test mail as in the mail skill. The app's key or SMTP password is created by the user in the provider's dashboard and pasted into the server's `.env` by the user. Many hosting providers block or throttle outgoing ports 25/465 (per-provider notes in `skills/server/providers.md`); 587 with STARTTLS or the HTTPS API works.

`mail.send_subdomain`: the subdomain column below; **empty** for providers that use none (Workspace, Brevo, Microsoft 365, own SMTP on the apex), so the audit runs with `--no-send-subdomain`. Check the provider's returned records when unsure.

| Provider | How golive talks to it | Typical records | SMTP (port 587) | Notes |
|---|---|---|---|---|
| **Resend** (default) | Bundled MCP `resend` | MX + SPF TXT on `send.`, DKIM TXT on `resend._domainkey` | `smtp.resend.com`, user `resend` | EU region `eu-west-1` |
| **Postmark** | Its API with the user's exported account token, or its MCP if connected | DKIM TXT (selector it gives), Return-Path CNAME (`pm-bounces.`) | `smtp.postmarkapp.com` | Separate message streams for transactional and broadcast mail |
| **Mailgun** | Its API with the user's exported key, or its official MCP if installed | SPF and DKIM TXT on the sending domain (often `mg.`), tracking CNAME, MX if it receives | `smtp.mailgun.org` (EU: `smtp.eu.mailgun.org`) | Pick the EU region at signup |
| **Amazon SES** | `aws sesv2` CLI with the user's profile (`create-email-identity` returns the DKIM tokens) | Three DKIM CNAMEs, custom MAIL FROM (MX + SPF on a subdomain) | `email-smtp.<region>.amazonaws.com` | New accounts start in the sandbox; production access is a request in the AWS console (user step) |
| **Brevo** | Its API with the user's exported key, or its MCP if connected | Brevo verification TXT, DKIM, DMARC | `smtp-relay.brevo.com` | Also does newsletters: marketing mail needs consent under the users' law (see the `legal` skill) |
| **Google Workspace / Microsoft 365** (sending from real mailboxes) | Admin console, user step | SPF include, DKIM generated in the admin console | Their SMTP relay settings | Not meant for bulk transactional mail |
| **Own SMTP server** | Mail skill section D | SPF `ip4:`, DKIM from the server, PTR | own host | Port 25 unblock request to the hosting provider; weakest deliverability at first |
