# Registrars: how golive works with each

The registrar is `domain.registrar` in `.claude/golive.yaml`, chosen by the user in `init` (or here). Porkbun is only the default suggestion. Whatever the registrar, the same rules hold: show first-year and renewal price, dry run or checkout link when available, explicit yes before paying, auto-renew and transfer lock on afterwards. API keys never go into the chat or the state file: the user exports them in their own terminal.

| Registrar | How golive talks to it | Buy | Point nameservers at Cloudflare | Notes |
|---|---|---|---|---|
| **Porkbun** (default) | Bundled MCP `porkbun` (OAuth) | `check_domain`, dry run, `register_domain` | Porkbun MCP nameserver tool, or its "move to Cloudflare" | Paid from prepaid credit; default monthly spend limit |
| **Namecheap** | Bundled MCP `namecheap` (OAuth; grant read-write at sign-in) | `domains_check_availability`, then `domain_purchase_link` (checkout link, safest) or `domain_register` | `domain_set_nameservers` | MX through its DNS tools only with Custom MX |
| **Cloudflare Registrar** | Bundled MCP `cloudflare` | Registrar API (beta): limited extensions, charges the card on file, no renewals through the API | Nothing to do: the zone is already on Cloudflare | At-cost prices; also a good transfer target later |
| **GoDaddy** | REST API with the user's key (`GODADDY_KEY`, `GODADDY_SECRET` exported by the user) via `curl`, or the panel | Availability and purchase endpoints of its Domains API | Domain update endpoint, or the panel | GoDaddy limits API access on small accounts; if refused, use the panel (user step) |
| **Country-code TLDs with local rules** (e.g. `.com.tr` through TRABIS-accredited Turkish registrars, `.eu` needs EU residence, `.us` a US nexus, `.ca` Canadian presence) | The accredited local registrar's panel or API, often a user step | The user registers it (the registry's eligibility rules apply) | Claude gives the two Cloudflare nameservers; the user enters them | Claude verifies the change with `audit.py` |
| **Any other registrar** (Gandi, Name.com, Dynadot, OVH, IONOS, Hostinger, ...) | Its MCP if the user has one connected, else its API with the user's exported key, else the panel | As the registrar offers | As the registrar offers | Same confirmation rules; the guard asks before purchases on any MCP tool that registers, renews or transfers a domain |
| **Already owned** | – | Skip buying | Per the registrar's row above | Record the registrar; check DNSSEC (DS) before switching (dns skill) |

Unused bundled connectors can stay disconnected: turn them off in `/mcp` (Claude Code) or leave them "Not connected" under Customize → Plugins → golive → Connectors.
