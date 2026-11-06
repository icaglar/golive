---
name: legal
description: Prepares the legal go-live items for the jurisdictions where the company is and where its users are - EU/EEA (GDPR, ePrivacy cookies, SCCs), UK (UK GDPR, PECR, ICO fee), US (CCPA/CPRA and other state laws, CAN-SPAM, COPPA), Canada (PIPEDA, CASL), Brazil (LGPD), Turkey (KVKK, İYS, ETBİS) and others - as drafts (privacy notice, cookie policy, processor list, terms) plus a checklist for a lawyer to confirm. Use for the legal go-live step, or when the user says "privacy policy", "GDPR", "cookie banner", "legal pages", "terms of service", "KVKK metni", "yasal sayfalar".
---

# Legal items

Talk to the user in the language they use; write the drafts in the language(s) of the site's users. These are **drafts and a checklist, not legal advice**: say so once, and mark the step done only after the user confirms a lawyer or privacy professional reviewed them.

## 1. Scope

Read `legal` and `profile.data_residency` in `.claude/golive.yaml`; if unset, ask with `AskUserQuestion`. Plugin defaults (empty if the user set none): company country `${user_config.default_company_country}`, user regions `${user_config.default_user_regions}`. If set, offer them as the first, "(Recommended)" answer; the project can still choose differently.
1. **Where is the company (data controller) established?** (country)
2. **Where are the users?** (multi-select: EU/EEA, UK, US, Canada, Brazil, Turkey, other)
3. **What does the app do?** (multi-select: collects accounts/personal data; sends marketing e-mail or SMS; sells online; serves children; hosts user content)

Then scan the code: forms and fields (name, e-mail, phone, address, IDs, health or other sensitive data), cookies and third-party scripts (analytics, ads, chat widgets), payment, newsletters. Ask for the controller's legal name, address, registration number and contact e-mail instead of inventing them; leave `[…]` placeholders where unknown. Record everything under `legal:` in the state file.

## 2. Drafts (into `legal/` in the repo)

1. **Privacy notice**: who the controller is, what data, purposes, legal bases (where the law requires them), recipients and processors, international transfers, retention, users' rights and how to exercise them, contact (and DPO/representative where required).
2. **Cookie policy and banner rules**: strictly necessary cookies need no consent in most places; analytics/ads/marketing cookies need prior opt-in consent in the EU/EEA, UK and Turkey: "Reject" as easy as "Accept", no pre-ticked boxes, nothing optional loaded before consent. US: disclose, and honour opt-out signals (Global Privacy Control) where state laws require it.
3. **Processors and transfers table** (`legal/processors.md`): each service, what it processes, where: hosting (`server_defaults.provider` and each `servers:` location), the DNS/CDN provider (e.g. Cloudflare terminates TLS and sees traffic wherever its edge is), the registrar, the mail provider (`mail.provider`, region), backup storage including the offsite copy (`database.offsite`), GitHub, analytics, error tracking, monitoring (Grafana Cloud if used), payment. Compare each location with `profile.data_residency`: a processor outside the chosen region is a transfer, so record the mechanism (adequacy decision, standard contractual clauses or the jurisdiction's equivalent) and whether a signed data processing agreement exists. If a processor cannot meet the residency requirement, flag it and suggest the provider's in-region option (check the provider docs) before the lawyer review.
4. **Terms of service** (and, for online sales, the pre-contract information, withdrawal/refund policy and seller identity required where the users are).

## 3. Checklist (in the step note and `legal/checklist.md`)

Build it from `${CLAUDE_PLUGIN_ROOT}/skills/legal/jurisdictions.md`: the common items below, plus each selected jurisdiction's rows.

- [ ] Privacy notice and cookie policy linked from every page; consent banner wired in where required.
- [ ] Data processing agreements with every processor; transfer mechanism recorded for each transfer abroad.
- [ ] Marketing messages: consent where required, an unsubscribe in every message, consent records kept. Transactional messages (password reset, receipts) are separate.
- [ ] Users' rights: a way to request access, correction, deletion and export, and someone who answers within the legal deadline.
- [ ] Breach plan: who notifies the authority and users, within which deadline (72 hours under GDPR and KVKK).
- [ ] Retention: how long each kind of data, logs and backups are kept; backups and logs are covered too.
- [ ] Accessibility: WCAG 2.1 AA is the usual target (the `design` / accessibility review can check pages).
- [ ] Children: if the service may be used by children, the age rules of each jurisdiction.

Set `steps.legal` to `blocked` with `owner: user` until the review, then `done`.
