#!/usr/bin/env python3
"""golive status board: where the go-live stands, what is next, what is missing.

Reads .claude/golive.yaml (PyYAML if installed, else a small built-in parser for the
golive state format) and prints a board for the chat, or writes a standalone HTML page.

Usage:
  status.py [--state .claude/golive.yaml] [--lang tr|en] [--format text|html|json] [--out file.html]
"""
import argparse
import datetime as dt
import html
import json
import os
import re
import sys

PHASES = [
    ("domain_phase", ["domain", "nameservers"]),
    ("infra", ["environments", "server", "cluster", "database", "deploy"]),
    ("release", ["tls", "dns_records", "ci_cd", "migrate"]),
    ("mail", ["mail_send", "mail_inbound", "app_config"]),
    ("operations", ["ops", "monitoring"]),
    ("compliance", ["legal", "launch", "audit"]),
]

T = {
    "tr": {
        "domain_phase": "Alan adı", "infra": "Altyapı", "release": "Yayın", "mail": "Mail",
        "operations": "Operasyon", "compliance": "Uyum ve kontrol",
        "domain": "Domain", "nameservers": "Nameserver", "environments": "Ortamlar", "server": "Sunucu",
        "cluster": "Cluster", "database": "Veritabanı", "deploy": "Deploy", "tls": "TLS", "dns_records": "DNS geçişi",
        "ci_cd": "CI/CD", "migrate": "Taşıma", "mail_send": "Mail gönderimi", "mail_inbound": "Gelen mail", "app_config": "Uygulama ayarı",
        "ops": "Yedek ve ops", "monitoring": "İzleme", "legal": "Yasal", "launch": "Canlı hazırlık", "audit": "Son kontrol",
        "done": "tamam", "in_progress": "devam ediyor", "pending": "bekliyor", "blocked": "takıldı", "skipped": "atlandı",
        "next": "Sıradaki", "waiting_you": "Senden beklenenler", "missing": "Eksikler", "none": "yok",
        "remaining": "adım kalan", "all_done": "Tüm adımlar tamam. Canlıya hazır.", "updated": "Güncellendi",
        "no_state": "Durum dosyası yok: önce /golive:init çalıştırın.", "progress": "ilerleme", "per_month": "ay",
    },
    "en": {
        "domain_phase": "Domain", "infra": "Infrastructure", "release": "Release", "mail": "Mail",
        "operations": "Operations", "compliance": "Compliance and checks",
        "domain": "Domain", "nameservers": "Nameservers", "environments": "Environments", "server": "Server",
        "cluster": "Cluster", "database": "Database", "deploy": "Deploy", "tls": "TLS", "dns_records": "DNS cutover",
        "ci_cd": "CI/CD", "migrate": "Migration", "mail_send": "Sending mail", "mail_inbound": "Inbound mail", "app_config": "App config",
        "ops": "Backups and ops", "monitoring": "Monitoring", "legal": "Legal", "launch": "Launch readiness", "audit": "Final audit",
        "done": "done", "in_progress": "in progress", "pending": "pending", "blocked": "blocked", "skipped": "skipped",
        "next": "Next", "waiting_you": "Waiting for you", "missing": "Missing", "none": "none",
        "remaining": "steps left", "all_done": "All steps done. Ready to go live.", "updated": "Updated",
        "no_state": "No state file: run /golive:init first.", "progress": "progress", "per_month": "month",
    },
}

ICON = {"done": "✅", "in_progress": "🔄", "pending": "⏳", "blocked": "⛔", "skipped": "➖"}


# Canonical step order (the `next` skill defines it; order_steps() adapts it to the project).
BASE_ORDER = ["domain", "nameservers", "environments", "server", "cluster", "database", "deploy", "tls",
              "dns_records", "ci_cd", "migrate", "mail_send", "mail_inbound", "app_config", "ops",
              "monitoring", "legal", "launch", "audit"]
K8S_RUNTIMES = ("hetzner-k3s", "kube-hetzner", "managed-k8s", "k3sup")
ENV_STEPS = ("server", "deploy", "tls", "dns_records")


# ---------- reading the state ----------

def _scalar(value):
    value = value.strip()
    if value and value[0] in "\"'":
        q = value[0]
        end = value.find(q, 1)
        return value[1:end] if end > 0 else value[1:]
    value = re.split(r"\s+#", value, maxsplit=1)[0].strip()
    if value.startswith("{"):
        return _flow_map(value)
    if value.startswith("["):
        return _flow_list(value)
    if value in ("", "null", "~"):
        return None
    if value in ("true", "false"):
        return value == "true"
    return value


def _split_top(body):
    """Split on commas that are not inside quotes, braces or brackets."""
    parts, buf, quote, depth = [], "", None, 0
    for ch in body:
        if quote:
            buf += ch
            if ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
            buf += ch
        elif ch in "{[":
            depth += 1
            buf += ch
        elif ch in "}]":
            depth -= 1
            buf += ch
        elif ch == "," and depth == 0:
            parts.append(buf)
            buf = ""
        else:
            buf += ch
    parts.append(buf)
    return [p for p in parts if p.strip()]


def _inner(text, open_ch, close_ch):
    """Text between the first open_ch and its matching close_ch (comments after it are dropped)."""
    text = text.strip()
    depth, quote = 0, None
    for i, ch in enumerate(text):
        if quote:
            if ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
        elif ch == open_ch:
            depth += 1
        elif ch == close_ch:
            depth -= 1
            if depth == 0:
                return text[1:i]
    return text[1:]


def _flow_map(body):
    out = {}
    for part in _split_top(_inner(body, "{", "}") if body.strip().startswith("{") else body):
        if ":" in part:
            k, v = part.split(":", 1)
            out[k.strip().strip("\"'")] = _scalar(v) if v.strip() else ""
            if out[k.strip().strip("\"'")] is None:
                out[k.strip().strip("\"'")] = ""
    return out


def _flow_list(body):
    return [_scalar(p) for p in _split_top(_inner(body, "[", "]"))]


def parse_state(text):
    """Minimal parser for the golive state file: top-level sections with scalar keys, flow maps
    (nested), flow lists, block lists of flow maps (costs) and steps."""
    state, section, step = {}, None, None
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip(" "))
        if indent == 0:
            m = re.match(r"^([\w-]+):\s*(.*)$", line)
            if not m:
                continue
            key, rest = m.group(1), m.group(2)
            if rest and not rest.startswith("#"):
                state[key] = _scalar(rest)
                section = None
            else:
                section = key
                state[section] = {}
            step = None
            continue
        if section is None:
            continue
        stripped = line.strip()
        if stripped.startswith("- ") or stripped == "-":  # block list item (costs)
            if not isinstance(state[section], list):
                state[section] = []
            item = _scalar(stripped[1:].strip()) if stripped != "-" else None
            state[section].append(item)
            continue
        if not isinstance(state[section], dict):
            continue
        m = re.match(r"^\s+([\w-]+):\s*(.*)$", line)
        if not m:
            continue
        key, rest = m.group(1), m.group(2).strip()
        if indent == 2:
            if rest == "" or rest.startswith("#"):
                state[section][key] = {}
                step = key
            else:
                value = _scalar(rest)
                state[section][key] = value if value is not None else None
                step = None
        elif indent >= 4 and step is not None and isinstance(state[section].get(step), dict):
            value = _scalar(rest)
            state[section][step][key] = "" if value is None else value
    return state


def load_state(path):
    with open(path, encoding="utf-8") as f:
        text = f.read()
    if os.environ.get("GOLIVE_NO_PYYAML") != "1":
        try:
            import yaml  # type: ignore
            data = yaml.safe_load(text)
            if isinstance(data, dict):
                return data
        except Exception:
            pass
    return parse_state(text)


# ---------- model ----------

def _truthy(value):
    return value is True or str(value).strip().lower() in ("true", "yes", "1")


def _dict(value):
    return value if isinstance(value, dict) else {}


def order_steps(state):
    """The ONE ordering function (text, html and json all use it). Returns the step names in the order they run.

    default (Cloudflare DNS): ... deploy, tls, [migrate], dns_records, ci_cd ...
    no Cloudflare:            ... deploy, [migrate], dns_records, tls, ci_cd ...
    k8s runtimes:             ... cluster, database, ci_cd, tls (done by cluster), [migrate], dns_records ... (server, deploy skipped)
    migrate sits before the dns_records cutover and only applies when profile.replaces_live_app.
    """
    dns = str(_dict(state.get("domain")).get("dns_provider") or "cloudflare").strip().lower()
    runtime = str(state.get("runtime") or "compose").strip().lower()
    order = [s for s in BASE_ORDER if s != "migrate"]
    if runtime in K8S_RUNTIMES:
        pre = ["domain", "nameservers", "environments", "server", "deploy", "cluster", "database", "ci_cd", "tls"]
        order = pre + [s for s in order if s not in pre]
    elif dns != "cloudflare":
        order.remove("dns_records")
        order.insert(order.index("tls"), "dns_records")
    order.insert(order.index("dns_records"), "migrate")
    return order


def _applicable(state, name):
    """False for steps that do not apply to this project (so they cannot be 'next')."""
    runtime = str(state.get("runtime") or "compose").strip().lower()
    if name in ("server", "deploy"):
        return runtime not in K8S_RUNTIMES
    if name == "cluster":
        return runtime in K8S_RUNTIMES
    if name == "migrate":
        return _truthy(_dict(state.get("profile")).get("replaces_live_app"))
    return True


def _norm_status(value):
    status = str(value or "pending").strip().lower()
    return status if status in ICON else "pending"


def _env_names(state, envs):
    names = [e for e in ("staging", "prod") if e in envs] + [e for e in envs if e not in ("staging", "prod")]
    if str(_dict(state.get("environments")).get("layout") or "") == "prod-only":
        names = [e for e in names if e != "staging"]
    return names


def _row(state, phase, name, info):
    info = info if isinstance(info, dict) else {"status": str(info)}
    status = _norm_status(info.get("status"))
    envs = {}
    raw_envs = info.get("envs")
    if isinstance(raw_envs, dict):
        for e in _env_names(state, raw_envs):
            envs[str(e)] = _norm_status(raw_envs[e])
    if name in BASE_ORDER and not _applicable(state, name) and status == "pending":
        status = "skipped"
    elif envs and status not in ("skipped", "blocked"):
        values = list(envs.values())
        complete = all(v in ("done", "skipped") for v in values)
        if complete:
            status = "skipped" if all(v == "skipped" for v in values) else "done"
        elif status == "done" or (status == "pending" and any(v in ("done", "in_progress") for v in values)):
            status = "in_progress"
    return {"phase": phase, "step": name, "status": status, "owner": str(info.get("owner") or "claude"),
            "note": str(info.get("note") or ""), "envs": envs}


def collect_costs(state):
    """Sum costs[].monthly per currency; malformed entries are ignored."""
    totals = {}
    costs = state.get("costs")
    if not isinstance(costs, list):
        return totals
    for entry in costs:
        if not isinstance(entry, dict):
            continue
        cur = entry.get("currency")
        raw = entry.get("monthly")
        if not isinstance(cur, str) or not cur.strip() or isinstance(raw, bool):
            continue
        try:
            amount = float(raw)
        except (TypeError, ValueError):
            continue
        if amount != amount or amount in (float("inf"), float("-inf")) or amount < 0:
            continue
        cur = cur.strip().upper()
        totals[cur] = totals.get(cur, 0.0) + amount
    return totals


def cost_text(totals, t):
    if not totals:
        return ""
    return "≈ " + " + ".join(f"{amount:.2f} {cur}" for cur, amount in sorted(totals.items())) + "/" + t["per_month"]


def build(state):
    steps = dict(state.get("steps") or {})
    if "legal_tr" in steps:  # state files from golive < 0.9 used legal_tr
        steps.setdefault("legal", steps.pop("legal_tr"))
    phase_of = {n: p for p, names in PHASES for n in names}
    rows = []
    for name in order_steps(state):
        if name in steps:
            rows.append(_row(state, phase_of.get(name, "compliance"), name, steps[name]))
    known = {r["step"] for r in rows}
    for name, info in steps.items():  # steps the board does not know yet
        if name not in known and isinstance(info, dict):
            rows.append(_row(state, "compliance", name, info))
    applicable = [r for r in rows if r["status"] != "skipped"]
    done = [r for r in applicable if r["status"] == "done"]
    current = next((r for r in rows if r["status"] == "in_progress"), None)
    upcoming = next((r for r in rows if r["status"] == "pending"), None)  # blocked steps are never next
    waiting = [r for r in rows if r["status"] == "blocked"]
    missing = [r for r in rows if r["status"] in ("pending", "in_progress", "blocked")]
    domain = _dict(state.get("domain"))
    defaults = _dict(state.get("server_defaults")) or _dict(state.get("server"))  # old files: `server:`
    mail = _dict(state.get("mail"))
    context = [str(x) for x in [state.get("runtime"), defaults.get("provider"), domain.get("dns_provider"),
                                domain.get("registrar"), mail.get("provider")] if x]
    totals = collect_costs(state)
    return {
        "project": state.get("project") or "app",
        "domain": domain.get("name") or "",
        "context": context,
        "updated": str(state.get("updated") or ""),
        "order": [r["step"] for r in rows],
        "rows": rows, "done": len(done), "total": len(applicable),
        "current": current, "next": upcoming, "waiting": waiting, "missing": missing,
        "monthly_cost": {k: round(v, 2) for k, v in sorted(totals.items())},
    }


# ---------- renderers ----------

def bar(done, total, width=20):
    filled = round(width * done / total) if total else width
    return "█" * filled + "░" * (width - filled)


def label(r, t):
    """Step name, with per-environment progress when the step has envs: Deploy (staging ✅, prod ⏳)."""
    name = t.get(r["step"], r["step"])
    if r.get("envs") and r["status"] != "skipped":
        name += " (" + ", ".join(f"{e} {ICON[v]}" for e, v in r["envs"].items()) + ")"
    return name


def render_text(m, t):
    pct = round(100 * m["done"] / m["total"]) if m["total"] else 100
    out = [f"golive · {m['project']}" + (f" · {m['domain']}" if m["domain"] else "")
           + f"   {m['done']}/{m['total']} {bar(m['done'], m['total'])} {pct}%"]
    head = list(m["context"])
    cost = cost_text(m["monthly_cost"], t)
    if cost:
        head.append(cost)
    if head:
        out.append(" · ".join(head))
    out.append("")
    width = max(len(t[p]) for p, _ in PHASES)
    for phase, _ in PHASES:
        cells = [f"{ICON.get(r['status'], '⏳')} {label(r, t)}" for r in m["rows"] if r["phase"] == phase]
        if cells:
            out.append(f"{t[phase]:<{width}}  " + "   ".join(cells))
    out.append("")
    if m["current"] or m["next"]:
        cur = m["current"] or m["next"]
        text = f"{label(cur, t)} ({t[cur['status']]})"
        after = m["next"] if m["current"] and m["next"] else None
        out.append(f"▶ {t['next']}: {text}" + (f" → {t.get(after['step'], after['step'])}" if after else ""))
    else:
        out.append(f"🎉 {t['all_done']}")
    if m["waiting"]:
        out.append(f"⛔ {t['waiting_you']}:")
        for r in m["waiting"]:
            out.append(f"   • {t.get(r['step'], r['step'])}: {r['note'] or t['blocked']}")
    left = [r for r in m["missing"] if r["status"] != "blocked"]
    if left:
        names = ", ".join(t.get(r["step"], r["step"]) for r in left)
        out.append(f"⏳ {t['missing']} ({len(left)} {t['remaining']}): {names}")
    return "\n".join(out)


def render_html(m, t, lang):
    pct = round(100 * m["done"] / m["total"]) if m["total"] else 100
    esc = html.escape
    phases_html = []
    for phase, _ in PHASES:
        chips = []
        for r in (r for r in m["rows"] if r["phase"] == phase):
            note = f'<span class="note">{esc(r["note"])}</span>' if r["note"] else ""
            owner = ' <span class="owner">👤</span>' if r["owner"] == "user" and r["status"] == "blocked" else ""
            envs = ""
            if r["envs"] and r["status"] != "skipped":
                envs = '<span class="envs">' + "".join(
                    f'<i class="env {v}">{esc(e)} {ICON[v]}</i>' for e, v in r["envs"].items()) + "</span>"
            chips.append(f'<li class="step {r["status"]}"><span class="st">{ICON.get(r["status"], "")} {esc(t[r["status"]])}</span>'
                         f'<b>{esc(t.get(r["step"], r["step"]))}</b>{owner}{envs}{note}</li>')
        if chips:
            phases_html.append(f'<section><h2>{esc(t[phase])}</h2><ol>{"".join(chips)}</ol></section>')
    nxt = m["current"] or m["next"]
    next_html = (f'<p class="next">▶ {esc(t["next"])}: <b>{esc(label(nxt, t))}</b> ({esc(t[nxt["status"]])})</p>'
                 if nxt else f'<p class="next">🎉 {esc(t["all_done"])}</p>')
    waiting_html = ""
    if m["waiting"]:
        items = "".join(f'<li><b>{esc(t.get(r["step"], r["step"]))}</b>: {esc(r["note"] or t["blocked"])}</li>' for r in m["waiting"])
        waiting_html = f'<div class="box warn"><h3>⛔ {esc(t["waiting_you"])}</h3><ul>{items}</ul></div>'
    left = [r for r in m["missing"] if r["status"] != "blocked"]
    missing_html = ""
    if left:
        items = "".join(f'<li>{esc(t.get(r["step"], r["step"]))}</li>' for r in left)
        missing_html = f'<div class="box"><h3>⏳ {esc(t["missing"])} ({len(left)} {esc(t["remaining"])})</h3><ul class="inline">{items}</ul></div>'
    stamp = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    ctx_parts = [esc(c) for c in m["context"]]
    cost = cost_text(m["monthly_cost"], t)
    if cost:
        ctx_parts.append(f'<span class="cost">{esc(cost)}</span>')
    ctx = " · ".join(ctx_parts)
    return f"""<!doctype html>
<html lang="{lang}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>golive · {esc(m['project'])}</title>
<style>
:root{{--bg:#f7f6f2;--card:#fdfcf9;--ink:#14213d;--muted:#4a5568;--line:#d9d6cc;--done:#1f7a4d;--prog:#2f6fb3;--block:#b3261e;--skip:#8a8f98;--accent:#f08a3c}}
@media (prefers-color-scheme:dark){{:root{{--bg:#0f1729;--card:#16213a;--ink:#eef0f4;--muted:#b8c2d6;--line:#2a3a5c;--done:#5cc28d;--prog:#7fb0e6;--block:#f2857b;--skip:#8a93a6}}}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:16px/1.45 system-ui,-apple-system,"Segoe UI",sans-serif;padding:24px 16px}}
main{{max-width:1100px;margin:0 auto}}h1{{font-size:28px;margin:0}}.ctx{{color:var(--muted);margin:4px 0 16px}}
.progress{{display:flex;align-items:center;gap:12px;margin:8px 0 20px}}.track{{flex:1;height:14px;background:var(--line);border-radius:8px;overflow:hidden}}
.fill{{height:100%;width:{pct}%;background:var(--accent)}}.pct{{font-weight:700;min-width:120px;text-align:right}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:16px}}
section{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px}}h2{{font-size:15px;text-transform:uppercase;letter-spacing:.06em;color:var(--muted);margin:0 0 10px}}
ol{{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:8px}}
.step{{border-left:4px solid var(--line);padding:6px 10px;border-radius:6px;background:var(--bg)}}.step b{{display:block}}
.step .st{{font-size:13px;color:var(--muted)}}.note{{display:block;font-size:13px;color:var(--muted);overflow-wrap:anywhere}}
.envs{{display:flex;flex-wrap:wrap;gap:6px;margin-top:4px}}.env{{font-style:normal;font-size:12px;border:1px solid var(--line);border-radius:10px;padding:0 8px;background:var(--card)}}
.cost{{font-weight:600;color:var(--ink)}}.step b,h1{{overflow-wrap:anywhere}}
.done{{border-color:var(--done)}}.in_progress{{border-color:var(--prog)}}.blocked{{border-color:var(--block)}}.skipped{{border-color:var(--skip);opacity:.7}}
.next{{font-size:18px;margin:20px 0 12px}}.box{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px 16px;margin:12px 0}}
.box.warn{{border-color:var(--block)}}.box h3{{margin:0 0 6px;font-size:16px}}.inline{{display:flex;flex-wrap:wrap;gap:8px;list-style:none;margin:6px 0 0;padding:0}}.inline li{{background:var(--bg);border:1px solid var(--line);border-radius:14px;padding:2px 12px}}
footer{{color:var(--muted);font-size:13px;margin-top:20px}}
</style></head><body><main>
<h1>golive · {esc(m['project'])}{(' · ' + esc(m['domain'])) if m['domain'] else ''}</h1>
<p class="ctx">{ctx}</p>
<div class="progress" role="img" aria-label="{m['done']} / {m['total']}"><div class="track"><div class="fill"></div></div><div class="pct">{m['done']}/{m['total']} · {pct}%</div></div>
<div class="grid">{''.join(phases_html)}</div>
{next_html}{waiting_html}{missing_html}
<footer>{esc(t['updated'])}: {stamp}</footer>
</main></body></html>
"""


def main():
    ap = argparse.ArgumentParser(description="golive status board")
    ap.add_argument("--state", default=os.path.join(os.environ.get("CLAUDE_PROJECT_DIR", "."), ".claude", "golive.yaml"))
    ap.add_argument("--lang", choices=["tr", "en"], default=os.environ.get("GOLIVE_LANG", "en"))
    ap.add_argument("--format", choices=["text", "html", "json"], default="text")
    ap.add_argument("--out", help="write the output to this file instead of stdout")
    args = ap.parse_args()
    t = T[args.lang]
    if not os.path.exists(args.state):
        print(t["no_state"])
        return
    model = build(load_state(args.state))
    if args.format == "html":
        output = render_html(model, t, args.lang)
    elif args.format == "json":
        output = json.dumps({k: v for k, v in model.items()}, ensure_ascii=False, indent=2, default=str)
    else:
        output = render_text(model, t)
    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(output)
    else:
        print(output)


if __name__ == "__main__":
    main()
