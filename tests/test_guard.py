#!/usr/bin/env python3
"""Tests for scripts/guard.py. Run: python3 tests/test_guard.py"""
import json
import os
import subprocess
import sys
import unittest

GUARD = os.path.join(os.path.dirname(__file__), "..", "scripts", "guard.py")


def run(payload, env=None):
    proc = subprocess.run(
        [sys.executable, GUARD],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env={**os.environ, **(env or {})},
    )
    assert proc.returncode == 0, proc.stderr
    out = proc.stdout.strip()
    return json.loads(out)["hookSpecificOutput"]["permissionDecision"] if out else None


def bash(cmd, env=None):
    return run({"tool_name": "Bash", "tool_input": {"command": cmd}}, env)


def run_full(payload, env=None):
    proc = subprocess.run(
        [sys.executable, GUARD], input=json.dumps(payload), capture_output=True, text=True, env={**os.environ, **(env or {})}
    )
    assert proc.returncode == 0, proc.stderr
    return proc.stdout.strip()


def mcp_full(name, args=None):
    return run_full({"tool_name": name, "tool_input": args or {}})


def json_reason(out):
    """(decision, reason) from a guard output; (None, "") when it printed nothing."""
    if not out:
        return None, ""
    data = json.loads(out)["hookSpecificOutput"]
    return data["permissionDecision"], data["permissionDecisionReason"]


def mcp(name, args=None, env=None):
    return run({"tool_name": name, "tool_input": args or {}}, env)


class Bash(unittest.TestCase):
    def test_server_create_asks(self):
        self.assertEqual(bash("hcloud server create --name app-1 --type cx23 --image ubuntu-24.04 --enable-protection delete,rebuild"), "ask")

    def test_global_flag_before_subcommand(self):
        self.assertEqual(bash("hcloud --context prod server delete app-1"), "ask")

    def test_firewall_replace_asks(self):
        self.assertEqual(bash("hcloud firewall replace-rules golive-web --rules-file r.json"), "ask")

    def test_free_resources_pass(self):
        for cmd in (
            "hcloud ssh-key create --name me --public-key-from-file ~/.ssh/id_ed25519.pub",
            "hcloud firewall create --name golive-web --rules-file /tmp/r.json",
            "hcloud server list -o json | jq '.[0]'",
            "hcloud server set-rdns app-1 --ip 1.2.3.4 --hostname app.example.com",
            "hcloud server-type list",
        ):
            self.assertIsNone(bash(cmd), cmd)

    def test_chained_command_segment(self):
        self.assertEqual(bash("hcloud server list && hcloud volume create --name data --size 10"), "ask")

    def test_curl_delete_cloudflare(self):
        self.assertEqual(bash('curl -X DELETE "https://api.cloudflare.com/client/v4/zones/z/dns_records/r" -H "Authorization: Bearer $T"'), "ask")

    def test_curl_get_cloudflare_passes(self):
        self.assertIsNone(bash('curl -s "https://api.cloudflare.com/client/v4/zones" -H "Authorization: Bearer $T"'))

    def test_curl_porkbun_register(self):
        self.assertEqual(bash("curl -s -X POST https://api.porkbun.com/api/json/v3/domain/create/example.com -d @body.json"), "ask")

    def test_unrelated_delete_passes(self):
        self.assertIsNone(bash("curl -X DELETE http://localhost:8000/api/items/3"))
        self.assertIsNone(bash("rm -rf build && git status"))

    def test_gh(self):
        self.assertEqual(bash("gh repo deploy-key delete 123"), "ask")
        self.assertEqual(bash("gh repo delete owner/app --yes"), "ask")
        for cmd in ("gh repo deploy-key add /tmp/k.pub --title app-1", "gh workflow run deploy.yml", "gh run view 1 --log-failed", "gh repo create app --private --source . --push"):
            self.assertIsNone(bash(cmd), cmd)

    def test_production_release(self):
        self.assertEqual(bash("gh workflow run release.yml -f environment=production -f sha=abc123"), "ask")
        self.assertIsNone(bash("gh workflow run release.yml -f environment=staging -f sha=abc123"))
        self.assertIsNone(bash("gh workflow run ci.yml"))

    def test_k8s(self):
        self.assertEqual(bash("hetzner-k3s create --config infra/cluster.yaml | tee create.log"), "ask")
        self.assertEqual(bash("hetzner-k3s delete --config infra/cluster.yaml"), "ask")
        self.assertEqual(bash("kubectl delete namespace staging"), "ask")
        self.assertEqual(bash("kubectl -n prod delete pvc data-db-0"), "ask")
        self.assertEqual(bash("tofu apply"), "ask")
        for cmd in ("kubectl get nodes", "kubectl -n prod delete pod web-123", "kubectl create namespace prod", "hetzner-k3s releases"):
            self.assertIsNone(bash(cmd), cmd)

    def test_database(self):
        for cmd in (
            "ssh deploy@db-1 \"sudo -u postgres psql -c 'DROP DATABASE app'\"",
            "docker compose exec -T db psql -U app -c 'truncate table users'",
            "sudo -u postgres psql -c 'SELECT pg_promote();'",
            "sudo pg_ctlcluster 17 main promote",
            "mysql -e 'STOP REPLICA; RESET REPLICA ALL;'",
            "dropdb app_staging",
        ):
            self.assertEqual(bash(cmd), "ask", cmd)
        for cmd in (
            "sudo -u postgres psql -c 'SELECT client_addr, state, replay_lag FROM pg_stat_replication;'",
            "pg_basebackup -h 10.0.0.2 -U replicator -D /var/lib/postgresql/17/main -R -X stream -C -S db2",
            "hcloud network create --name golive-net --ip-range 10.0.0.0/16",
        ):
            self.assertIsNone(bash(cmd), cmd)

    def test_other_clouds(self):
        for cmd in (
            "doctl compute droplet create app-prod --size s-2vcpu-4gb --image ubuntu-24-04-x64 --region fra1 --user-data-file ci.yaml",
            "doctl compute droplet delete app-prod --force",
            "vultr-cli instance create --region fra --plan vc2-2c-4gb --os 2284",
            "linode-cli linodes create --type g6-standard-2 --region eu-central",
            "aws lightsail create-instances --instance-names app --blueprint-id ubuntu_24_04 --bundle-id small_3_0",
            "aws ec2 terminate-instances --instance-ids i-123",
            "scw instance server create type=DEV1-S image=ubuntu_noble",
        ):
            self.assertEqual(bash(cmd), "ask", cmd)
        for cmd in ("doctl compute droplet list", "doctl auth init", "aws lightsail get-instances", "scw instance server list"):
            self.assertIsNone(bash(cmd), cmd)

    def test_terraform(self):
        self.assertEqual(bash("terraform apply -auto-approve"), "ask")

    def test_option_off(self):
        # Claude Code exports options upper-cased.
        self.assertIsNone(bash("hcloud server delete app-1", env={"CLAUDE_PLUGIN_OPTION_GUARD": "false"}))

    def test_line_continuation(self):
        self.assertEqual(bash("hcloud \\\n  server delete app-1"), "ask")
        self.assertEqual(bash("hcloud --context prod \\\n  server create --name a --type t --image ubuntu-24.04"), "ask")

    def test_enable_protection_passes(self):
        self.assertIsNone(bash("hcloud server enable-protection app-1 delete rebuild"))

    def test_disable_protection_asks(self):
        self.assertEqual(bash("hcloud server disable-protection app-1 delete rebuild"), "ask")


class BashRound1(unittest.TestCase):
    def asks(self, *cmds):
        for cmd in cmds:
            self.assertEqual(bash(cmd), "ask", cmd)

    def passes(self, *cmds):
        for cmd in cmds:
            self.assertIsNone(bash(cmd), cmd)

    def test_billable(self):
        self.asks(
            "doctl databases create app-db --engine pg --size db-s-1vcpu-1gb --region fra1",
            "doctl databases resize app-db --size db-s-2vcpu-4gb",
            "doctl kubernetes cluster create k --region fra1",
            "doctl compute load-balancer create --name lb --region fra1",
            "scw k8s cluster create name=k type=kapsule",
            "scw lb lb create name=lb",
            "aws s3 mb s3://my-bucket --region eu-central-1",
            "aws s3api create-bucket --bucket b --endpoint-url https://fsn1.your-objectstorage.com",
            "helm install ingress-nginx ingress-nginx/ingress-nginx -n ingress --create-namespace",
            "helm upgrade --install cnpg cnpg/cloudnative-pg -n cnpg-system",
            "helm --kube-context prod upgrade -i kps prometheus-community/kube-prometheus-stack",
            "hcloud load-balancer create --name lb --type lb11 --location fsn1",
            "s3cmd mb s3://backups",
            "mc mb hetzner/backups",
        )
        self.passes(
            "helm list -A",
            "helm template x ./chart",
            "helm repo add ingress-nginx https://kubernetes.github.io/ingress-nginx",
            "helm upgrade app ./chart",
            "aws s3 ls",
            "aws s3 cp x s3://b/x",
            "doctl databases list",
            "scw k8s cluster list",
            "hcloud load-balancer list",
        )

    def test_data_deletion(self):
        self.asks(
            "kubectl delete cluster.postgresql.cnpg.io app-db -n prod",
            "kubectl -n prod delete clusters.postgresql.cnpg.io app-db",
            "kubectl delete -k k8s/overlays/prod",
            "kubectl delete -f infra/prod/db.yaml",
            "docker compose down -v",
            "docker compose -f compose.yaml down --remove-orphans --volumes",
            "docker-compose down -v",
            "docker volume rm app_pgdata",
            "docker volume prune -f",
            "docker system prune -a --volumes",
            "sudo rm -rf /var/lib/postgresql/17/main",
            "rm -rf /var/lib/mysql",
            "ssh deploy@db-1 'sudo systemctl stop postgresql && sudo rm -rf /var/lib/postgresql/17'",
            "ssh deploy@app 'rm -r -f /srv/app/data'",
            "restic forget --keep-daily 7 --prune",
            "restic -r s3:x/y prune",
            "gh api -X DELETE repos/o/app/environments/prod",
            "gh api --method delete repos/o/app",
            "gh api repos/o/app/git/refs/heads/x --method DELETE",
        )
        self.passes(
            "kubectl delete pod web-1",
            "kubectl delete -f k8s/overlays/staging/x.yaml",
            "kubectl delete -k k8s/overlays/staging",
            "docker compose down",
            "docker compose down --remove-orphans",
            "docker compose up -d --remove-orphans",
            "docker volume ls",
            "docker image prune -f",
            "rm -rf build node_modules",
            "rm -rf /tmp/x",
            "ls /var/lib/postgresql",
            "restic snapshots",
            "restic forget --keep-daily 7 --dry-run --prune",
            "gh api repos/x/y",
            "gh api -X POST repos/x/y/issues -f title=t",
        )

    def test_prod_release_outside_workflow_run(self):
        self.asks(
            "gh api repos/o/app/actions/workflows/release.yml/dispatches -f ref=main -f 'inputs[environment]=production'",
            "gh api repos/o/app/dispatches -f event_type=deploy-prod",
            "echo '{\"ref\":\"main\",\"inputs\":{\"environment\":\"prod\"}}' | gh api repos/o/app/actions/workflows/r.yml/dispatches --input -",
            "gh api repos/o/app/actions/workflows/r.yml/dispatches --input payload.json",
            "docker buildx imagetools create -t ghcr.io/o/app:prod ghcr.io/o/app:sha-abc",
            "docker buildx imagetools create --tag ghcr.io/o/app:production ghcr.io/o/app:sha-abc",
            "git push origin golive-prod --force",
            "git push -f origin refs/tags/golive-prod",
            "git tag -f golive-prod abc123",
            "git tag golive-prod abc123 -f",
        )
        self.passes(
            "gh api repos/o/app/actions/workflows/release.yml/dispatches -f ref=main -f 'inputs[environment]=staging'",
            "docker buildx imagetools create -t ghcr.io/o/app:staging ghcr.io/o/app:sha-abc",
            "docker buildx imagetools inspect ghcr.io/o/app:prod",
            "git push origin main",
            "git push origin golive-staging --force",
            "git tag -f golive-staging abc123",
            "git tag -l golive-prod",
            "git ls-remote --tags origin golive-prod",
            "git log golive-prod..main",
        )

    def test_cloudflare_curl_dns(self):
        base = "https://api.cloudflare.com/client/v4/zones/z"
        self.asks(
            f"curl -X POST {base}/dns_records -H 'Authorization: Bearer $T' -d @r.json",
            f"curl -X PUT {base}/dns_records/r1 -d '{{}}'",
            f"curl --request PATCH {base}/dns_records/r1 -d '{{}}'",
            f"curl {base}/dns_records -H 'X: y' --data @r.json",
            f"curl -X POST {base}/email/routing/dns -H 'Authorization: Bearer $T'",
            f"curl -X POST {base}/email/routing/enable",
        )
        self.passes(
            f"curl -s {base}/dns_records -H 'Authorization: Bearer $T'",
            f"curl -s -X GET {base}/dns_records?name=x",
            f"curl -s {base}/email/routing -H 'Authorization: Bearer $T'",
            f"curl -X POST {base}/firewall/rules -d @r.json",
        )


class Mcp(unittest.TestCase):
    def test_porkbun_register(self):
        self.assertEqual(mcp("mcp__plugin_golive_porkbun__register_domain", {"domain": "example.com"}), "ask")

    def test_porkbun_register_dry_run_passes(self):
        self.assertIsNone(mcp("mcp__plugin_golive_porkbun__register_domain", {"domain": "example.com", "dry_run": True}))

    def test_porkbun_check_passes(self):
        self.assertIsNone(mcp("mcp__plugin_golive_porkbun__check_domain", {"domain": "example.com"}))

    def test_auto_renew_passes(self):
        self.assertIsNone(mcp("mcp__plugin_golive_porkbun__update_auto_renew", {"status": "on"}))

    def test_namecheap_register(self):
        self.assertEqual(mcp("mcp__namecheap__domain_register", {"domain": "x.com"}), "ask")

    def test_dns_delete(self):
        self.assertEqual(mcp("mcp__porkbun__delete_dns_record", {"id": 1}), "ask")

    def test_nameserver_change(self):
        self.assertEqual(mcp("mcp__porkbun__update_nameservers", {"ns": ["a", "b"]}), "ask")
        self.assertEqual(mcp("mcp__namecheap__domain_set_nameservers", {"ns": ["a", "b"]}), "ask")

    def test_resend_remove_domain(self):
        self.assertEqual(mcp("mcp__plugin_golive_resend__remove_domain", {"id": "d"}), "ask")

    def test_resend_send_passes(self):
        self.assertIsNone(mcp("mcp__plugin_golive_resend__send_email", {"to": "a@b.c"}))

    def test_cloudflare_code_delete(self):
        code = "await cloudflare.request({method: 'DELETE', path: `/zones/${z}/dns_records/${r}`})"
        self.assertEqual(mcp("mcp__plugin_golive_cloudflare__execute", {"code": code}), "ask")

    def test_cloudflare_code_delete_variants(self):
        for code in (
            'await cloudflare.request({method: "DELETE", path: `/zones/${z}/dns_records/${r}`})',
            "await cloudflare.request({method: `DELETE`, path: p})",
            "await fetch(url, {method: 'delete'})",
            'await cf.post(`/zones/${z}/dns_records/batch`, {deletes: [{id: r}]})',
            "DELETE /zones/${z}",
            "await client.dns.records.delete(r, {zone_id: z})",
        ):
            self.assertEqual(mcp("mcp__plugin_golive_cloudflare__execute", {"code": code}), "ask", code)

    def test_porkbun_create_domain(self):
        self.assertEqual(mcp("mcp__porkbun__create_domain", {"domain": "x.com"}), "ask")

    def test_create_dns_record_passes(self):
        self.assertIsNone(mcp("mcp__porkbun__create_dns_record", {"type": "A"}))

    def test_cloudflare_code_registrar(self):
        code = "await cf.post(`/accounts/${a}/registrar/registrations`, {domain_name: 'example.com'})"
        self.assertEqual(mcp("mcp__plugin_golive_cloudflare__execute", {"code": code}), "ask")

    def test_cloudflare_code_create_record_asks(self):
        # 1.0: any live DNS write is confirm-worthy, even during initial setup
        code = "await cf.post(`/zones/${z}/dns_records`, {type: 'A', name: '@', content: '1.2.3.4', proxied: true})"
        self.assertEqual(mcp("mcp__plugin_golive_cloudflare__execute", {"code": code}), "ask")

    def test_github_trigger_passes(self):
        self.assertIsNone(mcp("mcp__plugin_golive_github__actions_run_trigger", {"method": "run_workflow", "workflow_id": "deploy.yml"}))
        self.assertIsNone(mcp("mcp__plugin_golive_github__actions_list", {"method": "list_workflow_runs"}))
        self.assertIsNone(mcp("mcp__plugin_golive_github__create_repository", {"name": "app", "private": True}))

    def test_github_production_trigger_asks(self):
        args = {"method": "run_workflow", "workflow_id": "release.yml", "inputs": {"environment": "production", "sha": "abc"}}
        self.assertEqual(mcp("mcp__plugin_golive_github__actions_run_trigger", args), "ask")
        args["inputs"]["environment"] = "staging"
        self.assertIsNone(mcp("mcp__plugin_golive_github__actions_run_trigger", args))

    def test_github_delete_method_asks(self):
        self.assertEqual(mcp("mcp__plugin_golive_github__actions_run_trigger", {"method": "delete_workflow_run_logs", "run_id": 1}), "ask")
        self.assertEqual(mcp("mcp__plugin_golive_github__delete_file", {"path": "x"}), "ask")

    def test_any_registrar_purchase_asks(self):
        self.assertEqual(mcp("mcp__dynadot__register_domain", {"domain": "x.com"}), "ask")
        self.assertEqual(mcp("mcp__somereg__domains_purchase", {"domain": "x.com"}), "ask")
        self.assertEqual(mcp("mcp__plugin_golive_namecheap__domain_register", {"domain": "x.com"}), "ask")
        self.assertIsNone(mcp("mcp__somereg__check_domain_availability", {"domain": "x.com"}))
        self.assertIsNone(mcp("mcp__slack__register_webhook", {"url": "x"}))

    def test_namecheap_purchase_link_passes(self):
        # a checkout link charges nothing; the user pays on the website
        self.assertIsNone(mcp("mcp__plugin_golive_namecheap__domain_purchase_link", {"domain": "x.com"}))

    def test_unrelated_server_passes(self):
        self.assertIsNone(mcp("mcp__Gmail__trash_message", {"id": "1"}))


class McpRound1(unittest.TestCase):
    CF = "mcp__plugin_golive_cloudflare__execute"

    def test_cloudflare_dns_code_writes_ask(self):
        for code in (
            "await cloudflare.request({method: 'PATCH', path: `/zones/${z}/dns_records/${r}`, body})",
            "await cloudflare.request({method: \"PUT\", path: `/zones/${z}/dns_records/${r}`})",
            "await client.dns.records.create({zone_id: z, type: 'MX', name: '@', content: 'mx.x', priority: 10})",
            "await client.dns.records.update(r, {zone_id: z, type: 'A', name: '@', content: '1.2.3.4'})",
            "await cf.put(`/zones/${z}/dns_records/${r}`, body)",
        ):
            reason = json_reason(mcp_full(self.CF, {"code": code}))
            self.assertIn("ask", reason[0], code)
            self.assertIn("site and mail", reason[1], code)

    def test_cloudflare_dns_code_reads_pass(self):
        for code in (
            "await cf.get(`/zones/${z}/dns_records`)",
            "await cloudflare.request({method: 'GET', path: `/zones/${z}/dns_records?name=x`})",
            "await client.dns.records.list({zone_id: z})",
            "await cf.post(`/zones/${z}/firewall/rules`, body)",
        ):
            self.assertIsNone(mcp(self.CF, {"code": code}), code)

    def test_email_routing_enable_asks(self):
        for code in (
            "await cf.post(`/zones/${z}/email/routing/enable`)",
            "await client.emailRouting.enable(z, {})",
            "await cf.post(`/zones/${z}/email/routing/dns`, {})",
        ):
            reason = json_reason(mcp_full(self.CF, {"code": code}))
            self.assertEqual(reason[0], "ask", code)
            self.assertIn("MX", reason[1], code)
        self.assertIsNone(mcp(self.CF, {"code": "await cf.get(`/zones/${z}/email/routing`)"}))

    def test_cloudflare_dns_tool_names(self):
        self.assertEqual(mcp("mcp__plugin_golive_cloudflare__create_dns_record", {"type": "A"}), "ask")
        self.assertEqual(mcp("mcp__cloudflare__update_dns_record", {"id": "1"}), "ask")
        self.assertEqual(mcp("mcp__cloudflare__enable_email_routing", {"zone": "z"}), "ask")
        self.assertIsNone(mcp("mcp__cloudflare__list_dns_records", {"zone": "z"}))
        # other registrars' record tools keep passing
        self.assertIsNone(mcp("mcp__porkbun__create_dns_record", {"type": "A"}))

    def test_github_overlays_prod_write_asks(self):
        for tool, args in (
            ("create_or_update_file", {"path": "k8s/overlays/prod/kustomization.yaml", "content": "x", "message": "m"}),
            ("push_files", {"files": [{"path": "k8s/overlays/prod/image.yaml", "content": "x"}], "message": "m"}),
        ):
            self.assertEqual(mcp("mcp__plugin_golive_github__" + tool, args), "ask", tool)
        self.assertIsNone(mcp("mcp__plugin_golive_github__create_or_update_file", {"path": "k8s/overlays/staging/kustomization.yaml", "content": "x"}))
        self.assertIsNone(mcp("mcp__plugin_golive_github__get_file_contents", {"path": "k8s/overlays/prod/kustomization.yaml"}))

    def test_unknown_server_destructive_asks(self):
        for name in (
            "mcp__digitalocean__delete_droplet",
            "mcp__digitalocean__destroy_database_cluster",
            "mcp__vultr__remove_firewall_rule",
            "mcp__linode__terminate_instance",
            "mcp__someprovider__purge_bucket",
            "mcp__someprovider__delete_dns_record",
            "mcp__someprovider__delete_zone",
            "mcp__someprovider__create_droplet",
            "mcp__someprovider__resize_volume",
            "mcp__someprovider__create_load_balancer",
            "mcp__someprovider__create_bucket",
            "mcp__someprovider__create_database",
        ):
            self.assertEqual(mcp(name, {"id": "1"}), "ask", name)

    def test_unknown_server_harmless_passes(self):
        for name in (
            "mcp__digitalocean__list_droplets",
            "mcp__digitalocean__get_database",
            "mcp__Gmail__trash_thread",
            "mcp__Gmail__delete_label",
            "mcp__slack__delete_message",
            "mcp__Google_Calendar__delete_event",
            "mcp__Supabase__delete_branch",
            "mcp__someprovider__create_ticket",
            "mcp__sessions__delete_session",
        ):
            self.assertIsNone(mcp(name, {"id": "1"}), name)
        self.assertIsNone(mcp("mcp__someprovider__delete_droplet", {"dry_run": True}))


class StateFile(unittest.TestCase):
    def write(self, content, path="/repo/.claude/golive.yaml"):
        return run({"tool_name": "Write", "tool_input": {"file_path": path, "content": content}})

    def test_template_passes(self):
        template = os.path.join(os.path.dirname(__file__), "..", "templates", "golive.yaml")
        with open(template, encoding="utf-8") as f:
            self.assertIsNone(self.write(f.read()))

    def test_resend_key_denied(self):
        self.assertEqual(self.write("secrets:\n  resend: re_" + "AbCdEf1234567890xyzABC\n"), "deny")

    def test_hetzner_token_denied(self):
        self.assertEqual(self.write("token: " + "a1B2" * 16 + "\n"), "deny")

    def test_private_key_denied(self):
        self.assertEqual(self.write("-----BEGIN OPENSSH " + "PRIVATE KEY-----\nabc\n"), "deny")

    def test_edit_denied(self):
        payload = {"tool_name": "Edit", "tool_input": {"file_path": "x/golive.yaml", "old_string": "a", "new_string": "api_key: sk_" + "live_0123456789abcdefghijklmn"}}
        self.assertEqual(run(payload), "deny")

    def test_other_files_untouched(self):
        self.assertIsNone(self.write("RESEND_API_KEY=re_" + "AbCdEf1234567890xyzABC\n", path="/repo/.env"))

    def test_secret_block_ignores_option(self):
        self.assertEqual(
            run({"tool_name": "Write", "tool_input": {"file_path": "golive.yaml", "content": "re_" + "AbCdEf1234567890xyzABC"}},
                env={"CLAUDE_PLUGIN_OPTION_GUARD": "false"}),
            "deny",
        )

    def test_github_tokens_denied(self):
        for tok in (
            "ghp_" + "a1B2c3D4e5" * 4,
            "gho_" + "a1B2c3D4e5" * 4,
            "ghu_" + "a1B2c3D4e5" * 4,
            "ghs_" + "a1B2c3D4e5" * 4,
            "ghr_" + "a1B2c3D4e5" * 4,
            "github_pat_11ABCDEFG0" + "a1B2c3D4e5" * 6,
        ):
            self.assertEqual(self.write(f"ci_cd:\n  note: {tok}\n"), "deny", tok)

    def test_cloudflare_token_denied(self):
        tok = "AbCdEfGhIj0123456789KlMnOpQrStUvWxYz_-12"
        self.assertEqual(len(tok), 40)
        self.assertEqual(self.write(f"dns:\n  cf_key: {tok}\n"), "deny")
        self.assertEqual(self.write(f"cloudflare: \"{tok}\"\n"), "deny")
        self.assertEqual(self.write(f"secrets:\n  api: {tok}\n"), "deny")

    def test_git_sha_in_notes_passes(self):
        sha = "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b"
        self.assertEqual(len(sha), 40)
        self.assertIsNone(self.write(f"steps:\n  deploy:\n    note: pinned at {sha}\n"))
        self.assertIsNone(self.write(f"steps:\n  deploy:\n    note: \"{sha}\"\n"))
        self.assertIsNone(self.write(f"cloudflare_zone_id: {'a1' * 16}\n"))  # 32-char zone id is not a token

    def test_aws_keys_denied(self):
        self.assertEqual(self.write("aws_access_key_id: AKIA" + "IOSFODNN7EXAMPLE\n"), "deny")
        self.assertEqual(self.write("aws_secret_access_key: wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY\n"), "deny")
        self.assertEqual(self.write("secret_access_key = \"wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY\"\n"), "deny")
        self.assertIsNone(self.write("aws_secret_access_key_location: password manager entry aws-prod\n"))

    def test_telegram_token_denied(self):
        self.assertEqual(self.write("monitoring:\n  alerts: 123456789:AAH" + "x" * 32 + "\n"), "deny")
        self.assertIsNone(self.write("note: ticket 123456789 ok\n"))

    def test_url_credentials_denied(self):
        self.assertEqual(self.write("database:\n  prod: postgres://app:" + "S3cretPw@10.0.0.2:5432/app\n"), "deny")
        self.assertEqual(self.write("repo: https://user:" + "hunter2@github.com/o/r.git\n"), "deny")
        self.assertIsNone(self.write("database:\n  prod: postgres://app@10.0.0.2:5432/app\n"))
        self.assertIsNone(self.write("database:\n  prod: postgres://app:${DB_PASSWORD}@10.0.0.2/app\n"))
        self.assertIsNone(self.write("repo: https://github.com/o/r.git\n"))

    def bash_write(self, cmd):
        return bash(cmd)

    def test_bash_writes_with_secret_denied(self):
        tok = "ghp_" + "a1B2c3D4e5" * 4
        for cmd in (
            f"sed -i 's/token: null/token: {tok}/' .claude/golive.yaml",
            f"echo 'gh_token: {tok}' >> .claude/golive.yaml",
            f"printf 'x: %s' {tok} > golive.yaml",
            f"cat >> .claude/golive.yaml <<EOF\nsecrets:\n  gh: {tok}\nEOF",
            f"echo {tok} | tee -a .claude/golive.yaml",
            f"python3 -c \"open('.claude/golive.yaml','a').write('t: {tok}')\"",
            "echo 'k: postgres://a:" + "Pw123456@h/db' >> golive.yaml",
        ):
            self.assertEqual(bash(cmd), "deny", cmd)

    def test_bash_deny_ignores_option(self):
        tok = "ghp_" + "a1B2c3D4e5" * 4
        self.assertEqual(bash(f"echo 'a: {tok}' >> golive.yaml", env={"CLAUDE_PLUGIN_OPTION_GUARD": "false"}), "deny")

    def test_bash_clean_writes_pass(self):
        sha = "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b"
        for cmd in (
            "sed -i 's/status: pending/status: done/' .claude/golive.yaml",
            f"echo 'note: at {sha}' >> .claude/golive.yaml",
            "cat .claude/golive.yaml",
            "grep -n token .claude/golive.yaml",
            "echo ghp_" + "a1B2c3D4e5" * 4 + " > /tmp/other.txt",
        ):
            self.assertIsNone(bash(cmd), cmd)


class Robustness(unittest.TestCase):
    def test_garbage_input(self):
        proc = subprocess.run([sys.executable, GUARD], input="not json", capture_output=True, text=True)
        self.assertEqual((proc.returncode, proc.stdout), (0, ""))

    def test_kill_switch(self):
        self.assertIsNone(bash("hcloud server delete app-1", env={"GOLIVE_GUARD": "0"}))


if __name__ == "__main__":
    unittest.main(verbosity=1)
