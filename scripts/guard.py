#!/usr/bin/env python3
"""golive guard: PreToolUse hook.

- Asks for confirmation before actions that cost money or delete infrastructure:
  domain purchases/renewals/transfers, billable Hetzner resources, deletions,
  firewall rule replacements, DNS record deletions and nameserver changes.
- Denies writing secrets (API keys, tokens, private keys) into the golive state file.

Fails open: on any internal error it prints nothing and exits 0, so it never
blocks unrelated work. Disable with the plugin option `guard: false`
(cost/delete prompts only) or GOLIVE_GUARD=0 (everything).
"""
import json
import os
import re
import sys

PROVIDER_SERVERS = re.compile(
    r"porkbun|namecheap|cloudflare|resend|hetzner|hcloud|github|godaddy|gandi|dnsimple|route53|"
    r"namecom|name_com|dynadot|ovh|ionos|hostinger|natro|isimtescil|turhost|postmark|mailgun|brevo|sendgrid|(?<![a-z])ses(?![a-z])",
    re.I,
)
PROVIDER_HOSTS = re.compile(
    r"api\.cloudflare\.com|api\.porkbun\.com|porkbun\.com/api|api\.namecheap\.com|"
    r"api\.resend\.com|api\.hetzner\.cloud|api\.hetzner\.com|api\.godaddy\.com|"
    r"api\.gandi\.net|api\.dnsimple\.com|api\.name\.com|api\.dynadot\.com|api\.ovh\.com|"
    r"api\.postmarkapp\.com|api\.mailgun\.net|api\.eu\.mailgun\.net|api\.brevo\.com",
    re.I,
)

# MCP tool names (part after the server prefix), lowercased.
READ_ONLY_TOOL = re.compile(
    r"^(get|list|check|search|describe|read|find|lookup|query|fetch|preview|estimate|"
    r"whoami|docs?|verify|validate)(_|$)"
)
SPEND_TOOL = re.compile(
    r"register|renew|transfer|purchase|buy|checkout|top_?up|add_?funds|order|"
    r"create_domain|domains?_create"
)
# Domain purchases on ANY MCP server (registrar-agnostic), e.g. register_domain, domains_purchase, renew_domain.
ANY_DOMAIN_SPEND = re.compile(r"(regist|purchase|buy|renew|transfer|checkout).*domain|domain.*(regist|purchase|buy|renew|transfer|checkout)")
DESTROY_TOOL = re.compile(r"delete|remove|destroy|purge|revoke|disable")
NAMESERVER_TOOL = re.compile(r"nameserver|(^|_)ns(_|$)")
CHANGE_VERB = re.compile(r"set|update|change|replace|modify|edit|put")
CODE_TOOL = re.compile(r"(^|_)(execute|code)(_|$)|^run$")

# Code passed to a code-mode MCP tool (e.g. Cloudflare API MCP).
CODE_DELETE = re.compile(
    r"""['"`]delete['"`]|\.delete\s*\(|\bdeletes\s*['"]?\s*:|\bDELETE\s+/|-X\s*DELETE|--request[\s=]+DELETE""",
    re.I,
)
# Live DNS changes through a code-mode tool (Cloudflare): record writes and Email Routing enable (replaces MX).
DNS_MENTION = re.compile(r"dns[_./]records", re.I)
CODE_WRITE_VERB = re.compile(
    r"method\s*[:=]\s*['\"`]?(post|put|patch)\b|\.(post|put|patch)\s*\(|\.records\.(create|update|edit|batch|overwrite)\b|"
    r"\b(posts|puts|patches)\s*:|-X\s*(POST|PUT|PATCH)\b|dns_records/(batch|import)",
    re.I,
)
EMAIL_ROUTING = re.compile(r"email[_./-]?routing", re.I)
DNS_WRITE_TOOL = re.compile(r"(create|update|edit|patch|overwrite|batch|import|set|put|add|upsert).*(dns|record)|(dns|record).*(create|update|edit|patch|overwrite|batch|import|set|put|add|upsert)")
EMAIL_ROUTING_ENABLE_TOOL = re.compile(r"enable.*email|email.*enable|routing.*enable|enable.*routing")
# MCP servers that are not known providers: judge by tool name.
UNKNOWN_DESTROY_VERB = re.compile(r"delete|destroy|remove|terminate|purge")
UNKNOWN_DESTROY_NOUN = re.compile(r"droplet|server|instance|volume|database|cluster|zone|dns|record|domain|bucket|firewall|load_?balancer")
UNKNOWN_CREATE_VERB = re.compile(r"create|resize")
UNKNOWN_CREATE_NOUN = re.compile(r"droplet|server|instance|volume|database|cluster|load_?balancer|bucket")
# GitHub MCP tools that write files; a path under overlays/prod is a production release by commit.
GITHUB_WRITE_TOOL = re.compile(r"create_or_update_file|push_files|update_file|create_file|delete_file|edit_file|write_file|commit")
PROD_OVERLAY = re.compile(r"overlays/prod", re.I)

CODE_SPEND = re.compile(r"registrar[\s\S]{0,400}?(regist|renew|transfer|purchase)", re.I)

# Bash commands. Each pattern is matched against one command segment at a time.
HCLOUD_SPEND = re.compile(
    r"\bhcloud\b.*?\b(server|volume|primary-ip|floating-ip|load-balancer|storage-box)\s+"
    r"(create|create-image|change-type|enable-backup|attach-iso)\b"
)
HCLOUD_DESTROY = re.compile(
    r"\bhcloud\b.*?\b(delete|rebuild|reset|poweroff|shutdown|replace-rules|delete-rule|"
    r"remove-from-resource|detach|disable-protection|reset-password|remove-records?|"
    r"set-records|change-nameservers)\b"
)
HTTP_CLIENT = re.compile(r"\b(curl|wget|http|https|xh)\b")
HTTP_DELETE = re.compile(r"-X\s*DELETE|--request[\s=]+DELETE|\bhttps?\s+DELETE\b|\bDELETE\b")
HTTP_SPEND = re.compile(r"regist|purchase|renew|transfer|domain/create|domains\.create", re.I)
GH_DESTROY = re.compile(r"\bgh\b.*?\b(delete|archive)\b")
DB_DESTROY = re.compile(
    r"\bdrop\s+(database|schema|table)\b|\btruncate\s+(table\s+)?\w|\bdropdb\b|\bpg_promote\s*\(|"
    r"\bpg_ctl\b.*\bpromote\b|\bpg_ctlcluster\b.*\bpromote\b|\breset\s+replica\b|\bkubectl\b.*\bcnpg\b.*\bpromote\b",
    re.I,
)
PROD_RELEASE_CMD = re.compile(r"\bgh\s+workflow\s+run\b.*\bprod(uction)?\b")
K8S_SPEND = re.compile(r"\bhetzner-k3s\s+create\b")
K8S_DESTROY = re.compile(
    r"\bhetzner-k3s\s+delete\b|\bkubectl\b.*?\bdelete\s+(namespace|ns|pvc|pv|persistentvolume\w*)\b|"
    r"\bflux\s+uninstall\b|\bhelm\s+(uninstall|delete)\b"
)
DESTROY_VALUE = re.compile(r"^(delete|remove|destroy|purge)", re.I)
CLOUD_SPEND = re.compile(
    r"\bdoctl\b.*?\b(droplet|volume|database|kubernetes\s+cluster|load-balancer)\s+(create|resize)\b|"
    r"\bvultr-cli\b.*?\b(instance|block-storage|kubernetes|load-balancer)\s+create\b|"
    r"\blinode-cli\b.*?\b(linodes|volumes|lke|nodebalancers)\s+(create|resize|cluster-create)\b|"
    r"\baws\s+lightsail\s+create-(instances|disk|load-balancer|relational-database)|\baws\s+ec2\s+run-instances\b|"
    r"\bscw\b.*?\binstance\s+server\s+create\b"
)
BILLABLE_EXTRA = [
    (re.compile(r"\bdoctl\b.*?\b(droplet|volume|databases?|kubernetes|load-balancer|reserved-ip|snapshot|apps)\b.*?\b(create|resize)\b"), "DigitalOcean"),
    (re.compile(r"\bscw\b.*?\b(k8s\s+(cluster|pool)|lb\s+lb|rdb\s+instance|block\s+volume|instance\s+(server|volume|ip)|redis\s+cluster|object\s+bucket)\s+create\b"), "Scaleway"),
    (re.compile(r"\baws\b.*?\bs3\s+mb\b|\baws\b.*?\bs3api\s+create-bucket\b|\baws\b.*?\b(rds\s+create-db-(instance|cluster)|eks\s+create-(cluster|nodegroup)|elbv2\s+create-load-balancer|ec2\s+(create-volume|allocate-address))\b"), "AWS"),
    (re.compile(r"\b(s3cmd|mc|mcli)\s+mb\b|\brclone\s+mkdir\s+[\w.-]+:"), "an object storage bucket"),
]
HELM_INSTALL = re.compile(r"\bhelm\s+(?:--?[\w-]+(?:=\S+|\s+\S+)?\s+)*(install\b|upgrade\b.*\s(?:-i|--install)\b)")
CNPG_DELETE = re.compile(r"\bkubectl\b.*?\bdelete\b.*?(postgresql\.cnpg\.io|\bclusters?\b)|\bkubectl\s+cnpg\s+destroy\b")
KUBECTL_DELETE_PROD = re.compile(r"\bkubectl\b.*?\bdelete\b.*?(-k|-f|--kustomize|--filename)[\s=]+\S*prod", re.I)
COMPOSE_DOWN_V = re.compile(r"\bdocker[\s-]+compose\b.*?\bdown\b.*?(\s-[a-zA-Z]*v[a-zA-Z]*(?=\s|$)|--volumes\b)")
DOCKER_VOLUME_RM = re.compile(r"\bdocker\s+(volume\s+(rm|remove|prune)|(system|builder)\s+prune\b.*--volumes)\b")
RM_RECURSIVE = re.compile(r"\brm\b.*?(\s-[a-zA-Z]*[rR]|--recursive\b)")
DATA_PATH = re.compile(r"/var/lib/(postgresql|mysql|mariadb|docker/volumes|pgbackrest)|/srv/app\b|/mnt/(HC_Volume|data\b|volume)")
RESTIC_PRUNE = re.compile(r"\brestic\b.*?(\bprune\b|\bforget\b.*--prune)")
GH_API_DELETE = re.compile(r"\bgh\s+api\b.*?(-X\s*|--method[\s=]+)DELETE\b", re.I)
GH_API_DISPATCH = re.compile(r"\bgh\s+api\b[^\n]*\bdispatches\b|api\.github\.com[^\n]*\bdispatches\b")
PROD_WORD = re.compile(r"\bprod(uction)?\b", re.I)
IMAGE_PROD = re.compile(
    r"\bdocker\s+buildx\s+imagetools\s+create\b.*?(-t|--tag)[\s=]+\S*:prod(uction)?(?![\w.-])|"
    r"\bdocker\s+(push|tag)\b.*:prod(uction)?(?![\w.-])|\bcrane\s+(tag|copy|cp)\b.*\s\S*:?prod(uction)?\s*$"
)
PROD_TAG_MOVE = re.compile(
    r"\bgit\b.*?\bpush\b.*\bgolive-prod\b|\bgit\s+tag\b.*(\s-\w*f|--force).*\bgolive-prod\b|\bgit\s+tag\b.*\bgolive-prod\b.*(\s-\w*f\b|--force)|"
    r"\bgit\s+update-ref\b.*\bgolive-prod\b|\bgh\s+api\b.*\bgolive-prod\b.*(-X\s*|--method[\s=]+)(POST|PATCH|PUT)\b",
    re.I,
)
CURL_WRITE = re.compile(r"(-X\s*|--request[\s=]+)(POST|PUT|PATCH)\b|\bhttps?\s+(POST|PUT|PATCH)\b", re.I)
CURL_BODY = re.compile(r"\s(-d|--data\S*|--json)[\s=]")
CURL_GET_ONLY = re.compile(r"(-X\s*|--request[\s=]+)GET\b|\s-G\b", re.I)
CF_DNS_URL = re.compile(r"api\.cloudflare\.com\S*/dns_records", re.I)
CF_EMAIL_URL = re.compile(r"api\.cloudflare\.com\S*/email/routing/(enable|dns)", re.I)

CLOUD_DESTROY = re.compile(
    r"\bdoctl\b.*?\s(delete|rm)\b|\bvultr-cli\b.*?\s(delete|destroy)\b|\blinode-cli\b.*?\s(delete|rm)\b|"
    r"\baws\s+lightsail\s+delete-|\baws\s+ec2\s+terminate-instances\b|\baws\s+route53\s+change-resource-record-sets\b.*\bDELETE\b|"
    r"\bscw\b.*?\s(delete|terminate)\b"
)
IAC = re.compile(r"\b(terraform|tofu)\s+(apply|destroy)\b|\bpulumi\s+(up|destroy)\b")

SEGMENT_SPLIT = re.compile(r"&&|\|\||;|\||\n")
LINE_CONTINUATION = re.compile(r"\\\r?\n")
PROTECTION_ARGS = re.compile(r"(?<!dis)enable-protection(\s+|=)[\w,\s.-]*")

SECRET_PATTERNS = [
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"), "a private key"),
    (re.compile(r"\bre_[A-Za-z0-9_]{16,}"), "a Resend API key"),
    (re.compile(r"\b(pk1|sk1)_[A-Za-z0-9]{20,}"), "a Porkbun API key"),
    (re.compile(r"\b(ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{30,}|\bgithub_pat_[A-Za-z0-9_]{20,}"), "a GitHub token"),
    (re.compile(r"\b(AKIA|ASIA)[A-Z0-9]{16}\b"), "an AWS access key id"),
    (
        re.compile(r"(aws_?secret\w*|secret_?access_?key)[\"']?\s*[:=]\s*[\"']?[A-Za-z0-9/+=]{40}(?![A-Za-z0-9/+=])", re.I),
        "an AWS secret access key",
    ),
    (re.compile(r"(?<![\w:])\d{8,10}:[A-Za-z0-9_-]{35}(?![A-Za-z0-9_-])"), "a Telegram bot token"),
    (
        re.compile(
            r"\b[a-z][a-z0-9+.-]*://[^\s/:@\"'<>]+:(?!\$|\{|<|_{2}|%|\*|\.{3}|\[|x{3,}@|REDACTED|changeme|password@|pass@)[^\s/@\"'<>]+@[^\s/\"'<>]+",
            re.I,
        ),
        "a URL with an embedded password",
    ),
    (re.compile(r"\b[A-Za-z0-9]{64}\b"), "a 64-character token (Hetzner API tokens look like this)"),
    (
        re.compile(
            r"(token|secret|password|passwd|api[_-]?key)\s*[:=]\s*[\"']?[A-Za-z0-9_\-./+]{24,}",
            re.I,
        ),
        "a token or password value",
    ),
    # 40-character Cloudflare-style token assigned to a key; plain lowercase hex (a git SHA) is exempt.
    (
        re.compile(
            r"(cf|cloudflare|token|key|secret|password|passwd|api)[\w.-]*[\"']?\s*[:=]\s*[\"']?(?P<v>[A-Za-z0-9_-]{40})(?![A-Za-z0-9_-])",
            re.I,
        ),
        "a 40-character API token (Cloudflare tokens look like this)",
    ),
]
HEX_SHA = re.compile(r"^[0-9a-f]{40}$")


def find_secret(text: str):
    """Return a label for the first secret pattern found in text, else None."""
    for pattern, label in SECRET_PATTERNS:
        for m in pattern.finditer(text):
            v = m.groupdict().get("v")
            if v is not None and HEX_SHA.match(v):
                continue
            return label
    return None


BASH_STATE_WRITE = re.compile(
    r"\bsed\b[^|;&\n]*\s-\w*i|--in-place|\btee\b|>>?\s*[\"']?\S*golive\.ya?ml|\byq\b[^|;&\n]*\s-\w*i|"
    r"\bperl\b[^\n]*\s-\w*i|\bpython3?\b|\bcat\b[^\n]*<<|\bprintf\b|\becho\b|\bcp\b|\bmv\b|\bdd\b"
)


def option_enabled() -> bool:
    if os.environ.get("GOLIVE_GUARD") == "0":
        return False
    # Claude Code exports plugin options upper-cased: CLAUDE_PLUGIN_OPTION_GUARD.
    value = os.environ.get("CLAUDE_PLUGIN_OPTION_GUARD", os.environ.get("CLAUDE_PLUGIN_OPTION_guard"))
    if value is None:
        return True
    return value.strip().lower() not in ("false", "0", "no", "off")


def decision(kind: str, reason: str) -> None:
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": kind,
                    "permissionDecisionReason": f"golive guard: {reason}",
                }
            },
            ensure_ascii=False,
        )
    )
    sys.exit(0)


def is_dry_run(tool_input) -> bool:
    if not isinstance(tool_input, dict):
        return False
    for key, value in tool_input.items():
        if "dry" in key.lower() and value in (True, "true", "True", 1, "1"):
            return True
    return False


def check_mcp(tool_name: str, tool_input) -> None:
    parts = tool_name.split("__")
    if len(parts) < 3:
        return
    server = parts[1]
    tool = "__".join(parts[2:]).lower()
    if is_dry_run(tool_input):
        return
    if not PROVIDER_SERVERS.search(server):
        if not READ_ONLY_TOOL.search(tool) and "auto_renew" not in tool and not tool.endswith("_link") and ANY_DOMAIN_SPEND.search(tool):
            decision("ask", f"`{tool}` on {server} looks like a domain purchase, renewal or transfer. Confirm the domain, the price and the renewal price first.")
        if not READ_ONLY_TOOL.search(tool):
            if UNKNOWN_DESTROY_VERB.search(tool) and UNKNOWN_DESTROY_NOUN.search(tool):
                decision("ask", f"`{tool}` on {server} (not a known provider) looks like it deletes infrastructure or DNS. Check what it removes before confirming.")
            if UNKNOWN_CREATE_VERB.search(tool) and UNKNOWN_CREATE_NOUN.search(tool):
                decision("ask", f"`{tool}` on {server} (not a known provider) looks like it creates or resizes a billable resource. Confirm the size and price.")
        return

    if CODE_TOOL.search(tool):
        # Raw string values, not json.dumps: escaping turns "DELETE" into \"DELETE\".
        values = tool_input.values() if isinstance(tool_input, dict) else [tool_input]
        code = "\n".join(v if isinstance(v, str) else json.dumps(v, ensure_ascii=False) for v in values)
        if CODE_SPEND.search(code):
            decision("ask", f"`{tool}` on {server} looks like a registrar purchase, renewal or transfer. It charges money and cannot be refunded.")
        if CODE_DELETE.search(code):
            decision("ask", f"`{tool}` on {server} sends a DELETE request. Check what it removes before confirming.")
        if DNS_MENTION.search(code) and CODE_WRITE_VERB.search(code):
            decision("ask", f"`{tool}` on {server} creates or changes DNS records. Live DNS moves the site and mail: confirm the records and the zone.")
        if EMAIL_ROUTING.search(code) and (re.search(r"enable", code, re.I) or (re.search(r"/dns\b", code) and CODE_WRITE_VERB.search(code))):
            decision("ask", f"`{tool}` on {server} enables Email Routing, which replaces the zone's MX records. Live mail changes: confirm first.")
        return

    # Multi-action tools take the action as a parameter (e.g. GitHub's actions_run_trigger method=delete_workflow_run_logs).
    if isinstance(tool_input, dict):
        for key, value in tool_input.items():
            if isinstance(value, str) and DESTROY_VALUE.search(value.strip()) and key.lower() in ("method", "action", "operation", "op"):
                decision("ask", f"`{tool}` on {server} runs `{value}`. Check what it removes before confirming.")

    if "github" in server.lower() and GITHUB_WRITE_TOOL.search(tool) and PROD_OVERLAY.search(json.dumps(tool_input, ensure_ascii=False)):
        decision("ask", f"`{tool}` on {server} writes under overlays/prod, which releases to production. Confirm the commit you want live.")

    if "cloudflare" in server.lower() and not READ_ONLY_TOOL.search(tool):
        if DNS_WRITE_TOOL.search(tool):
            decision("ask", f"`{tool}` on {server} creates or changes DNS records. Live DNS moves the site and mail: confirm the records and the zone.")
        if EMAIL_ROUTING_ENABLE_TOOL.search(tool):
            decision("ask", f"`{tool}` on {server} enables Email Routing, which replaces the zone's MX records. Live mail changes: confirm first.")

    if "github" in server.lower() and "trigger" in tool and re.search(
        r"\bprod(uction)?\b", json.dumps(tool_input, ensure_ascii=False), re.I
    ):
        decision("ask", f"`{tool}` on {server} starts a production release. Confirm the commit you want live.")

    if READ_ONLY_TOOL.search(tool):
        return
    # A checkout link (e.g. Namecheap domain_purchase_link) charges nothing: the user pays on the website.
    if "auto_renew" not in tool and not tool.endswith("_link") and SPEND_TOOL.search(tool):
        decision("ask", f"`{tool}` on {server} can charge money (purchase, renewal, transfer or top-up). Confirm the domain, the price and the renewal price first.")
    if DESTROY_TOOL.search(tool):
        decision("ask", f"`{tool}` on {server} deletes or disables something. Check what it removes before confirming.")
    if NAMESERVER_TOOL.search(tool) and CHANGE_VERB.search(tool):
        decision("ask", f"`{tool}` on {server} changes nameservers. The site and mail follow the new DNS provider once this propagates.")


def check_bash(command: str) -> None:
    command = LINE_CONTINUATION.sub(" ", command)
    for segment in SEGMENT_SPLIT.split(command):
        seg = segment.strip()
        if not seg:
            continue
        if HCLOUD_SPEND.search(seg):
            decision("ask", f"`{seg[:120]}` creates or upgrades a billable Hetzner resource. Confirm the type, location and monthly price.")
        if HCLOUD_DESTROY.search(PROTECTION_ARGS.sub(" ", seg)):
            decision("ask", f"`{seg[:120]}` deletes, resets or reconfigures Hetzner infrastructure (a firewall replacement can lock you out).")
        if DB_DESTROY.search(seg):
            decision("ask", f"`{seg[:120]}` drops data or promotes a replica. Check which database and environment this is.")
        if PROD_RELEASE_CMD.search(seg):
            decision("ask", f"`{seg[:120]}` releases to production. Confirm the commit you want live.")
        if K8S_SPEND.search(seg):
            decision("ask", f"`{seg[:120]}` creates cluster nodes (and possibly load balancers) that are billed monthly.")
        if K8S_DESTROY.search(seg):
            decision("ask", f"`{seg[:120]}` deletes cluster resources (namespace, volumes, release or the whole cluster).")
        if GH_DESTROY.search(seg):
            decision("ask", f"`{seg[:120]}` deletes or archives something on GitHub (repo, deploy key, secret, release or run).")
        for pattern, who in BILLABLE_EXTRA:
            if pattern.search(seg):
                decision("ask", f"`{seg[:120]}` creates a billable resource ({who}). Confirm the size, region and monthly price.")
        if HELM_INSTALL.search(seg):
            decision("ask", f"`{seg[:120]}` installs a chart that may create load balancers or volumes (billed monthly). Check the values first.")
        if CNPG_DELETE.search(seg):
            decision("ask", f"`{seg[:120]}` deletes a Postgres cluster (CNPG) and possibly its data.")
        if KUBECTL_DELETE_PROD.search(seg):
            decision("ask", f"`{seg[:120]}` deletes production manifests from the cluster.")
        if COMPOSE_DOWN_V.search(seg) or DOCKER_VOLUME_RM.search(seg):
            decision("ask", f"`{seg[:120]}` deletes Docker volumes, which hold database data.")
        if RM_RECURSIVE.search(seg) and DATA_PATH.search(seg):
            decision("ask", f"`{seg[:120]}` recursively deletes a database or app data directory.")
        if RESTIC_PRUNE.search(seg) and "--dry-run" not in seg:
            decision("ask", f"`{seg[:120]}` permanently deletes backup snapshots.")
        if GH_API_DELETE.search(seg):
            decision("ask", f"`{seg[:120]}` sends a DELETE request to the GitHub API.")
        if IMAGE_PROD.search(seg):
            decision("ask", f"`{seg[:120]}` moves the production image tag. Confirm the image you want live.")
        if PROD_TAG_MOVE.search(seg):
            decision("ask", f"`{seg[:120]}` moves the golive-prod tag, which releases to production. Confirm the commit you want live.")
        if HTTP_CLIENT.search(seg) and "api.cloudflare.com" in seg.lower():
            writes = CURL_WRITE.search(seg) or (CURL_BODY.search(seg) and not CURL_GET_ONLY.search(seg))
            if writes and CF_DNS_URL.search(seg):
                decision("ask", f"`{seg[:120]}` creates or changes live DNS records (site and mail follow them). Confirm the records.")
            if writes and CF_EMAIL_URL.search(seg):
                decision("ask", f"`{seg[:120]}` enables Email Routing, which replaces the zone's MX records (live mail).")
        if CLOUD_SPEND.search(seg):
            decision("ask", f"`{seg[:120]}` creates or resizes a billable cloud resource. Confirm the size, region and monthly price.")
        if CLOUD_DESTROY.search(seg):
            decision("ask", f"`{seg[:120]}` deletes or terminates cloud resources or DNS records.")
        if IAC.search(seg):
            decision("ask", f"`{seg[:120]}` applies or destroys infrastructure.")
        if HTTP_CLIENT.search(seg) and PROVIDER_HOSTS.search(seg):
            if HTTP_DELETE.search(seg):
                decision("ask", f"`{seg[:120]}` sends a DELETE request to a provider API.")
            if HTTP_SPEND.search(seg):
                decision("ask", f"`{seg[:120]}` calls a registrar endpoint that can charge money.")


def check_bash_dispatch(command: str) -> None:
    # Whole command: the payload is often piped in from a previous segment.
    if GH_API_DISPATCH.search(command) and (PROD_WORD.search(command) or re.search(r"--input\b", command)):
        decision("ask", "a GitHub dispatch call mentions production (or hides its payload in --input). It can start a production release. Confirm the commit you want live.")


def check_bash_state_secret(command: str) -> None:
    if not re.search(r"golive\.ya?ml", command) or not BASH_STATE_WRITE.search(command):
        return
    label = find_secret(command)
    if label:
        decision(
            "deny",
            f"this command writes {label} into golive.yaml. The state file holds no secrets: "
            "record only where a secret lives (an environment variable name, a password manager entry, the server's .env).",
        )


def written_text(tool_name: str, tool_input: dict) -> str:
    if tool_name == "Write":
        return str(tool_input.get("content", ""))
    if tool_name == "Edit":
        return str(tool_input.get("new_string", ""))
    if tool_name == "MultiEdit":
        return "\n".join(str(e.get("new_string", "")) for e in tool_input.get("edits", []) or [])
    return ""


def check_state_file(tool_name: str, tool_input: dict) -> None:
    path = str(tool_input.get("file_path", ""))
    if not re.search(r"golive\.ya?ml$", path):
        return
    text = written_text(tool_name, tool_input)
    label = find_secret(text)
    if label:
        decision(
            "deny",
            f"this would write {label} into {os.path.basename(path)}. The state file holds no secrets: "
            "record only where a secret lives (an environment variable name, a password manager entry, the server's .env).",
        )


def main() -> None:
    if os.environ.get("GOLIVE_GUARD") == "0":
        return
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return
    tool_name = payload.get("tool_name") or ""
    tool_input = payload.get("tool_input") or {}

    if tool_name in ("Write", "Edit", "MultiEdit") and isinstance(tool_input, dict):
        check_state_file(tool_name, tool_input)
        return
    if tool_name == "Bash" and isinstance(tool_input, dict):
        check_bash_state_secret(str(tool_input.get("command", "")))
    if not option_enabled():
        return
    if tool_name == "Bash" and isinstance(tool_input, dict):
        check_bash_dispatch(str(tool_input.get("command", "")))
        check_bash(str(tool_input.get("command", "")))
    elif tool_name.startswith("mcp__"):
        check_mcp(tool_name, tool_input)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        sys.exit(0)
