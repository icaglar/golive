# DNS providers: Cloudflare or not

`domain.dns_provider` in `.claude/golive.yaml`. Cloudflare is the default and recommended, because several golive steps are built on its proxy. Without it everything still works, with these differences:

| Feature | With Cloudflare (default) | Without Cloudflare |
|---|---|---|
| Certificates | Origin CA certificate on the server, Full (strict) | Caddy gets and renews Let's Encrypt certificates itself (`templates/Caddyfile.letsencrypt`); the k8s ingress uses cert-manager with Let's Encrypt |
| Origin firewall | 80/443 only from Cloudflare | 80/443 open to everyone (`firewall_rules.py --public`) |
| Staging / Grafana protection | Cloudflare Access (e-mail codes), created by the dns skill | HTTP basic auth in Caddy or the ingress |
| WAF, rate limits, bot protection | Cloudflare rules (launch skill) | Rate limiting in the app or a Caddy plugin; no WAF unless the provider sells one |
| Inbound mail (info@, dmarc@) | Cloudflare Email Routing | The registrar's mail forwarding, or a mailbox provider |
| DDoS absorption, caching | Cloudflare edge | None beyond the server; keep static assets cacheable |
| DNSSEC | One click on Cloudflare + DS at the registrar | Wherever the DNS provider supports it |

How golive writes records without Cloudflare, per provider:

| DNS provider | How |
|---|---|
| The registrar's own DNS (Porkbun, Namecheap) | Their bundled MCPs' DNS tools |
| Hetzner DNS | `hcloud` zone/record commands where available, else Hetzner DNS API with the user's exported token |
| AWS Route 53 | `aws route53 change-resource-record-sets` with the user's profile |
| DigitalOcean, Vultr, Linode, Scaleway DNS | Their CLIs (`doctl compute domain records`, ...) |
| deSEC, Gandi, OVH, others | Their API with the user's exported token, or the panel (user step: Claude gives the exact records) |

Rules stay the same: upsert by name and type, one SPF record per name, mail records never behind a proxy, show and confirm before deleting a record (the guard asks), check DNSSEC before changing nameservers. Run `audit.py --dns-provider other` instead of the Cloudflare NS check.

Cutover without Cloudflare: lower the TTL (300 s) of the records you will change at least one old-TTL period before the switch, since there is no proxy to flip instantly; keep the old origin running until the new one is verified; raise the TTL afterwards. `dns_records` runs before `tls` so Let's Encrypt can validate.
