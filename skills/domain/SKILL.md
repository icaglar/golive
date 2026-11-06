---
name: domain
description: Finds, prices and buys a domain at the registrar the user chooses - Porkbun or Namecheap through their MCPs, Cloudflare Registrar, GoDaddy's API, a Turkish registrar for .com.tr, or any other registrar through its panel - with a dry run or checkout link and explicit confirmation before paying, then turns on auto-renew, WHOIS privacy and transfer lock. Use when the user wants to buy, register or check a domain, or says "domain al", "alan adı al", "domain boşta mı", "domain fiyatı", "Namecheap", "GoDaddy", "Natro".
---

# Buy a domain

Talk to the user in the language they use. Buying a domain charges money and cannot be undone, so the confirmation in step 4 is mandatory even if the user said "just buy it" earlier. How to talk to each registrar: `registrars.md` in this skill's folder (`${CLAUDE_PLUGIN_ROOT}/skills/domain/registrars.md`).

## 1. Registrar

Use `domain.registrar` from `.claude/golive.yaml`. If it is not set, ask with `AskUserQuestion`: Porkbun (default suggestion: MCP, prepaid credit, spend limit) / Namecheap / Cloudflare Registrar / another registrar (Other: type its name). Some country-code TLDs have eligibility rules or must be registered through local registrars (`.com.tr`, `.eu`, `.us`, `.ca`, ...): check registrars.md before suggesting one. If the domain is already owned, record the registrar, set `steps.domain: done` with "already owned at X" and stop.

## 2. Check names

With the registrar's tool (registrars.md), check availability and price. Show **first-year price and renewal price** side by side for each candidate; flag premium names. If the user has no name yet, suggest 5-10 short candidates across `.com`, `.app`, `.dev`, `.io` (and `.com.tr` if relevant) and check them in one batch. Prices differ by registrar: if the user is undecided, compare two registrars for the chosen name.

## 3. Dry run or checkout link

Porkbun: dry-run option first (exact cost, nothing charged); purchases come from account credit, so a low balance or the monthly spend limit can stop the order (user tops up or raises it on porkbun.com). Namecheap: prefer `domain_purchase_link`, which lets the user pay on namecheap.com. Panel registrars: give the user the exact name, years and options to pick, and wait until they say it is done.

## 4. Confirm, then buy

Show: domain, registrar, years, total now, renewal price per year, and that it is non-refundable. Ask a yes/no question. Only on an explicit yes call the registrar's purchase tool or API. The guard hook also asks; that second prompt is expected.

## 5. Secure it

Auto-renew on, WHOIS privacy on (free at most registrars; some ccTLD registries have their own rules), transfer lock on. Use the registrar's tools or list the panel settings for the user.

## 6. Record

In `.claude/golive.yaml`: `domain.name`, `domain.registrar`, `domain.owned: true`, `steps.domain: done` with a note like `bought 2026-11-06 at Namecheap, 1 year, renews $X/yr, auto-renew on`. Append a `costs:` entry for the yearly price: `{item: "domain <name>", monthly: <yearly / 12>, currency: <currency>, step: domain}` and say "yearly" in the note (e.g. `yearly 12.00`). Next comes the `nameservers` step (dns skill), which uses the same registrar row.
