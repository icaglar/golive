# Server providers: how golive works with each

`server_defaults.provider` in `.claude/golive.yaml`; Hetzner Cloud is only the default. The result must be the same everywhere: Ubuntu 24.04, a deploy user with key-only SSH, root login off, Docker, fail2ban, automatic security updates, a cloud firewall (or host rules) that opens 80/443 only to Cloudflare (or to everyone without Cloudflare) and SSH only to `server_defaults.ssh_from`, a private network for DB and monitoring where the provider has one.

CLI flags change between versions: **run the create command's `--help` first and adapt**, never guess a flag. Tokens come from the CLI's own login (`doctl auth init`, `aws configure`, ...) that the user runs in their own terminal; never in chat.

| Provider | CLI | Create with cloud-init | Firewall | Private network | Volumes | Reverse DNS | Outgoing mail ports |
|---|---|---|---|---|---|---|---|
| **Hetzner Cloud** (default) | `hcloud` | `server create --user-data-from-file` | Cloud Firewall (`firewall_rules.py`) | Networks | Volumes | `server set-rdns` | 25/465 blocked on new accounts |
| **DigitalOcean** | `doctl` | `compute droplet create --user-data-file` | Cloud Firewalls (`--format cidr-list`) | VPC (per region) | Volumes | From the droplet name (use an FQDN) | SMTP ports blocked on new accounts: use the mail provider's HTTPS API |
| **Vultr** | `vultr-cli` | `instance create` with user data | Firewall groups | VPC | Block storage | In the control panel / API | Port 25 blocked until a support request |
| **Linode (Akamai)** | `linode-cli` | `linodes create` with Metadata user data (regions that support it) | Cloud Firewall | VPC | Block storage | In the panel / API | SMTP restricted on new accounts |
| **AWS Lightsail** (or EC2) | `aws lightsail` (`aws ec2`) | `create-instances --user-data` | Instance firewall (security groups on EC2) | VPC peering / EC2 VPC | Block storage (EBS) | Request through AWS | Port 25 throttled until a request |
| **Scaleway** | `scw` | `instance server create` with `cloud-init=@file` | Security groups | Private networks | Block volumes | In the console | Port 25 blocked by default |
| **Any existing server / other VPS** (Turkish VPS providers, OVH, a dedicated box) | `ssh` | Run `${CLAUDE_PLUGIN_ROOT}/templates/bootstrap.sh` as root once (same result as the cloud-init) | Provider firewall if any, else `firewall_rules.py --format docker-user` (host rules that Docker cannot bypass) | WireGuard or the provider's private LAN, if needed | Provider's disks | Provider panel | Ask the provider |

Notes:
- Prices: show the monthly price from the provider's CLI or pricing page before creating, plus any separately billed IPv4.
- The guard asks before create, resize and delete commands of all these CLIs.
- Everything after the server step (deploy, TLS, database, monitoring) is the same on every provider: only SSH and private IPs matter.
- Kubernetes: the `cluster` skill's tools (hetzner-k3s, kube-hetzner) are Hetzner-only. On other providers use their managed Kubernetes (DOKS, LKE, EKS, Kapsule) or k3s installed with `k3sup` over SSH; the rest (namespaces, ingress, Flux, overlays) stays the same.

## Private network and volumes: creation per provider

Hetzner has exact commands in the `server` skill. For the others the commands change between CLI versions: use `--help` and "check the provider docs". Record each server's `private_ip`; the range goes in `server_defaults.private_range`.

| Provider | Private network / VPC | Block volume |
|---|---|---|
| **DigitalOcean** | `doctl vpcs create --region <r> --ip-range <range>`; give `--vpc-uuid` when creating droplets | `doctl compute volume create --size <GB> --region <r>`, then `doctl compute volume-action attach` (check the docs) |
| **Vultr** | `vultr-cli vpc create` (VPC 2.0 on newer plans); attach at instance creation (check the docs) | `vultr-cli block-storage create` then attach |
| **Linode** | `linode-cli vpcs create` plus a subnet; assign at creation (check the docs) | `linode-cli volumes create --linode_id <id> --size <GB>` |
| **AWS** | Lightsail: VPC peering; EC2: a VPC with a private subnet and security groups (check the docs) | `aws ec2 create-volume` then `attach-volume` (Lightsail: `aws lightsail create-disk`) |
| **Scaleway** | `scw vpc private-network create`, attach with `scw instance private-nic create` | `scw block volume create`, attach to the server |
| **Existing server / other VPS** | The provider's private LAN, else WireGuard between the machines (set `private_range` to it) | The provider's disk or panel |

When a provider has no private network, tunnel DB and monitoring traffic over WireGuard rather than exposing 5432/9100 publicly.

Load balancers (managed k8s, `cluster` skill): they may be reachable directly by IP, bypassing Cloudflare; restrict the allowed sources where the provider offers it (check the provider docs).
