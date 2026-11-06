---
name: cluster
description: Builds the Kubernetes cluster - k3s on Hetzner with hetzner-k3s or kube-hetzner, managed Kubernetes (DOKS, LKE, EKS, Kapsule) or k3s over SSH with k3sup on other providers - then staging and prod namespaces, an ingress behind a load balancer, TLS (Cloudflare Origin CA secret, or cert-manager with Let's Encrypt without Cloudflare), the Kustomize tree and Flux for pull-based GitOps deploys. Use for the cluster go-live step, or when the user says "k3s kur", "kubernetes cluster", "hetzner-k3s", "kube-hetzner", "k8s ortamı", "managed kubernetes".
---

# Kubernetes cluster

Talk to the user in the language they use. Read `runtime`, `environments`, `profile` and `server_defaults` from `.claude/golive.yaml`. Everything that creates nodes, load balancers or volumes costs money monthly: show node types, count and the load balancer, get a yes first (the guard also asks), and append each to `costs:` (`step: cluster`). Region follows `profile.data_residency`; `profile.budget` suggests masters (1 "lite" for minimal/balanced, 3 for high-availability) and whether staging gets its own cluster or a namespace.

**Ask `ssh_from` yourself** (the server step is skipped on k8s): find the user's IP with `curl --noproxy '*' -4 -s https://api.ipify.org`, confirm it, record `server_defaults.ssh_from`. It limits SSH and the Kubernetes API.

Prerequisites: `kubectl`, `helm`, the provider CLI (`hcloud`, `doctl`, `linode-cli`, `aws`, `scw`) logged in by the user in their own terminal; an SSH key without passphrase or a running agent. hetzner-k3s: `brew install vitobotta/tap/hetzner_k3s`; kube-hetzner: `brew install opentofu packer kubectl hcloud`.

## A. hetzner-k3s

1. Write `infra/cluster.yaml` (no token in it; `HCLOUD_TOKEN` comes from the user's environment):
   ```yaml
   cluster_name: <project>
   kubeconfig_path: "./kubeconfig"
   k3s_version: <pick from `hetzner-k3s releases`>
   networking:
     ssh: {port: <server_defaults.ssh_port>, use_agent: false, public_key_path: "~/.ssh/id_ed25519.pub", private_key_path: "~/.ssh/id_ed25519"}
     allowed_networks:
       ssh: [<server_defaults.ssh_from>]
       api: [<server_defaults.ssh_from>]
   masters_pool: {instance_type: <type>, instance_count: 1, locations: [<loc>]}   # 3 for HA
   worker_node_pools:
     - {name: workers, instance_type: <type>, instance_count: 2, location: <loc>}
   ```
   Types from `hcloud server-type list`. The user runs `hetzner-k3s create --config infra/cluster.yaml | tee create.log` (or you, after a yes). It installs the cloud controller, CSI driver, upgrade controller and autoscaler; no ingress.
2. `export KUBECONFIG=$PWD/kubeconfig`, `kubectl get nodes`; add `kubeconfig` to `.gitignore`.

## B. kube-hetzner

The user runs the project's setup script (interactive). Edit `kube.tf` (pools, location, SSH/API restricted to `ssh_from`). `tofu init --upgrade && tofu plan`, show the summary, `tofu apply` after a yes. `tofu output --raw kubeconfig > kubeconfig` (gitignored). Ingress (Traefik) and the load balancer come with the module; adapt the ingress class in the manifests if you keep Traefik.

## B2. Other providers

- **Managed Kubernetes** (DOKS `doctl kubernetes cluster create`, LKE `linode-cli lke cluster-create`, EKS `eksctl` or `aws eks`, Kapsule `scw k8s cluster create`): run `--help`, pick region, node size and count, show the price, create after a yes, fetch the kubeconfig with the provider's command. The control plane is the provider's; restrict API access where it offers an allow-list (check the provider docs).
- **k3s with k3sup**: servers from the `server` skill (one `role: k3s` machine per node, private network), then `k3sup install --ip <ip> --user <deploy_user> --ssh-key <key>` and `k3sup join` for workers; kubeconfig is written locally. Install a cloud-less ingress (ingress-nginx with `hostNetwork` or a NodePort behind the provider's load balancer).

## C. Common setup

1. **Namespaces**: `staging` and `prod` (or one cluster per environment if chosen).
2. **Ingress**: ingress-nginx via Helm (`ingressClassName: nginx`), Service type `LoadBalancer`; on Hetzner annotate `load-balancer.hetzner.cloud/location: <loc>`. The cloud controller creates a load balancer (billable: show it, append to `costs:`; a confirmation prompt is expected for `helm upgrade --install`). **A load balancer may be reachable directly by IP, bypassing Cloudflare** (and staging's Access): restrict allowed sources to Cloudflare's ranges where the provider supports it (check the provider docs; ingress-nginx `whitelist-source-range` annotation or `loadBalancerSourceRanges` are options).
3. **Manifests**: copy the whole tree to the app repo as `deploy/k8s/`: `${CLAUDE_PLUGIN_ROOT}/templates/k8s/base/`, `migrate/base/` (set `__MIGRATE_COMMAND__`), `overlays/{staging,prod}/` with their `migrate/` sub-overlays, `flux/kustomizations.yaml` (set `__ENV__` per environment and `__REPO__`; migrate-<env> runs before app-<env>) and, without Cloudflare, `cert-manager/`. One Deployment/Service per app service; images `ghcr.io/<owner>/<repo>-<service>`. `web.yaml` ships `sha-PLACEHOLDER` tags: `release.yml` pins the real `sha-<commit>`; nothing runs until then.
4. **TLS** (done here, so record `steps.tls: done` with the mode in the note; never `skipped`):
   - **Cloudflare (mode A)**: create the Origin CA key and certificate as in the `tls` skill (key generated locally in a temp dir), then `kubectl -n <ns> create secret tls origin-cert --cert=origin.pem --key=origin-key.pem` per namespace and delete the local files. Ingress uses `secretName: origin-cert`.
   - **No Cloudflare (mode B)**: `helm upgrade --install cert-manager jetstack/cert-manager -n cert-manager --create-namespace --set crds.enabled=true`, then apply `templates/k8s/cert-manager/` with `__ACME_EMAIL__` set (ClusterIssuers `letsencrypt-staging`, `letsencrypt-prod`); in `web.yaml` uncomment the `cert-manager.io/cluster-issuer: letsencrypt-prod` annotation and use `secretName: web-tls`. Test with `letsencrypt-staging` first. Record `steps.tls: done` ("cert-manager") once the Certificate is Ready; HTTP-01 needs the DNS records pointing at the load balancer, so on no-Cloudflare setups it turns Ready after `dns_records`; note that and re-check then.
5. **App secrets** never in Git or chat: generate in the command (`kubectl -n prod create secret generic app-env --from-literal=POSTGRES_PASSWORD="$(openssl rand -hex 24)"`); user-only values: the user runs the command.
6. **GHCR pull secret** (private images): the user creates a `read:packages` token and runs `kubectl -n <ns> create secret docker-registry ghcr --docker-server=ghcr.io --docker-username=<user> --docker-password=<token>`.
7. **GitOps with Flux** (pull-based; the API stays closed to `ssh_from`): `flux bootstrap github --owner=<profile.github.owner_type owner> --repository=<repo> --path=deploy/flux` and add `--personal` **only when `profile.github.owner_type` is `personal`**; for an org repo use the org form (no `--personal`; the token needs org access). `GITHUB_TOKEN` is exported by the user. Commit the Flux Kustomization pair from `flux/kustomizations.yaml` for each environment under `deploy/flux/` (the bootstrap path), so Flux picks it up.
8. **Database**: the `database` skill next (operator in the cluster or a DB server).

## D. Ready check and the load balancer IP

The app is not live until images exist: `ci_cd` builds them and `release.yml` pins `sha-<commit>`. After that run `kubectl -n <ns> rollout status deploy/<name>` for every Deployment (and the migrate Job succeeded). **Only when green** record the load balancer's public IP (`kubectl -n ingress-nginx get svc`) in the step note and hand it to `dns_records`; never before (ImagePullBackOff behind a live domain).

Set `steps.cluster: done` with node count/types, load balancer IP (not yet in DNS) and namespaces in the note. `server` and `deploy` are skipped on k8s. Next: `database`, `ci_cd`, then `tls`/`dns_records` per the order in the `next` skill.
