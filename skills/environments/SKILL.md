---
name: environments
description: Decides with the user how the app runs - environments layout (separate staging server, staging on the same server, or prod only), runtime (Docker Compose, k3s with hetzner-k3s or kube-hetzner, managed Kubernetes, or k3sup on any VPS), staging protection and mail sandbox - and records it, plus the servers to create, in .claude/golive.yaml so the server, cluster, deploy and workflow steps follow it. Use for the environments go-live step, or when the user says "staging ortamı kur", "staging ve prod", "k3s mi compose mu", "kubernetes kuralım", "ortamları ayarla".
---

# Environments and runtime

Talk to the user in the language they use. This step only decides and records; the `server`, `cluster`, `deploy` and `workflows` skills do the work. Read `profile` (budget, residency, app shape) first: init already derived defaults from it, so confirm them rather than asking again.

## 1. Ask

One `AskUserQuestion` form (max 4 questions), best guess first, marked "(Recommended)":

1. **Layout**: separate servers (staging and prod each on their own machine; recommended unless budget is minimal) / same server (both on one machine, cheaper, staging can starve prod) / prod only.
2. **Runtime**:
   - **Docker Compose** (recommended for a single app; cheapest and simplest).
   - **k3s with hetzner-k3s** or **k3s with kube-hetzner**: only on Hetzner; one CLI command or Terraform/OpenTofu builds the cluster.
   - **Managed Kubernetes** (the provider's own: DOKS, LKE, Scaleway Kapsule, ...): `managed-k8s`.
   - **k3sup on any VPS**: `k3sup`, for existing servers or providers without a managed offer.
   See `${CLAUDE_PLUGIN_ROOT}/skills/server/providers.md` for what each provider supports. One line of trade-off: Kubernetes pays off with several services, autoscaling or a team; for one app it is extra work and usually a load balancer more per month.
3. **Staging protection**: Cloudflare Access with e-mail one-time codes (recommended when DNS is on Cloudflare) / HTTP basic auth in Caddy or the ingress / none (public, noindex only).
4. **Staging mail**: a sandbox or test mode of the mail provider, or a separate API key limited to a few allowed recipients (recommended) / the same provider as prod with a catch-all recipient. Staging never mails real users.
Kubernetes only, as a short follow-up (the form is full): one cluster with `staging` and `prod` namespaces (recommended) / two clusters.

## 2. Record

```yaml
runtime: compose            # compose | hetzner-k3s | kube-hetzner | managed-k8s | k3sup
environments:
  layout: separate-servers  # separate-servers | same-server | prod-only
  staging: {host: staging.<domain>, image_tag: staging, protection: cloudflare-access}   # cloudflare-access | basic-auth | none
  prod: {host: <domain>, image_tag: prod}
```

Cloudflare Access is not created here: the `dns` skill creates the Access application in `dns_records`. Record only the protection choice.

Add the `servers:` entries to create (the `server` skill fills type, location and addresses), following layout and budget (`profile.budget`):

| Layout / budget | Entries |
|---|---|
| separate-servers | `app-staging` (env staging), `app-prod` (env prod) |
| same-server | `app-prod` only; staging runs on it (both Caddy blocks, `COMPOSE_FILE` per environment) |
| prod-only | `app-prod` |
| balanced and above, compose | `db-1` (role db-primary, env prod); staging keeps its database container |
| high-availability | `db-1` and `db-2` (role db-replica) |
| balanced and above | `mon-1` (role monitoring, env shared); minimal: none (Grafana Cloud free or uptime only) |

For k8s runtimes record nodes in the `cluster` step instead; `servers:` keeps only entries that are separate machines (database servers when not an operator).

Step changes:
- `compose`: the `server` and `deploy` steps run once per environment (staging first, smaller server type); `steps.cluster: skipped`. Set the `envs` sub-statuses: `{staging: pending, prod: pending}`, or `{prod: pending}` for prod-only.
- k8s runtimes: `steps.cluster` runs instead of `server` and `deploy` (set those two `skipped`, note "k8s"; TLS is done by `cluster`).
- prod only: drop the `staging` entry and every staging `envs` value.

## 3. Staging hygiene (whatever the runtime)

- Its own database and secrets; never prod data. Its own mail key or sandbox, and a visible "STAGING" marker in the app if possible.
- Not indexed: `X-Robots-Tag: noindex` (the staging Caddy block or ingress annotation does it).
- Protected as chosen above; the Access app or basic-auth hash is created later (dns_records / deploy).
- DNS: a `staging` record comes with the `dns_records` step.

Set `steps.environments: done` with the decisions in the note.
