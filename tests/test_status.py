#!/usr/bin/env python3
"""Tests for scripts/status.py. Run: python3 tests/test_status.py  (also with GOLIVE_NO_PYYAML=1)"""
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
import status  # noqa: E402

TEMPLATE = os.path.join(HERE, "..", "templates", "golive.yaml")
NO_YAML = os.environ.get("GOLIVE_NO_PYYAML") == "1"


def template():
    return Path(TEMPLATE).read_text(encoding="utf-8").replace("__PROJECT__", "crm").replace("__DOMAIN__", "ornek.com").replace("__DATE__", "2026-11-06")


def set_step(s, name, status_, owner="claude", note="", envs=None):
    env = ", envs: {%s}" % ", ".join(f"{k}: {v}" for k, v in envs.items()) if envs else ""
    new = '  %s {status: %s, owner: %s, note: "%s"%s}' % (name + ":", status_, owner, note, env)
    out, n = re.subn(r"(?m)^  %s:\s+\{.*\}$" % name, lambda m: new, s)
    assert n == 1, name
    return out


def load(text):
    """Parse like status.load_state does (PyYAML unless GOLIVE_NO_PYYAML=1)."""
    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False, encoding="utf-8") as f:
        f.write(text)
    try:
        return status.load_state(f.name)
    finally:
        os.unlink(f.name)


def model(text):
    return status.build(load(text))


def sample():
    s = template()
    for n in ("domain", "nameservers", "environments"):
        s = set_step(s, n, "done", note="ok")
    s = set_step(s, "server", "done", envs={"staging": "done", "prod": "done"})
    s = set_step(s, "deploy", "in_progress", envs={"staging": "done", "prod": "pending"})
    s = set_step(s, "cluster", "skipped", note="compose")
    s = set_step(s, "legal", "blocked", owner="user", note="avukat, onayı")
    return s


def nxt(m):
    return (m["current"] or m["next"] or {}).get("step")


class Board(unittest.TestCase):
    def test_sample(self):
        m = model(sample())
        self.assertEqual(m["done"], 4)  # domain, nameservers, environments, server (all envs done)
        self.assertEqual(m["current"]["step"], "deploy")
        self.assertEqual([r["step"] for r in m["waiting"]], ["legal"])
        self.assertEqual(m["waiting"][0]["note"], "avukat, onayı")
        text = status.render_text(m, status.T["tr"])
        self.assertIn("▶ Sıradaki: Deploy (staging ✅, prod ⏳)", text)
        self.assertIn("⛔", text)
        page = status.render_html(m, status.T["en"], "en")
        self.assertIn("<!doctype html>", page)
        self.assertIn("Waiting for you", page)
        self.assertIn("staging ✅", page)

    def test_total_counts_skipped_out(self):
        m = model(sample())
        # cluster skipped, migrate skipped (not replacing a live app)
        self.assertEqual(m["total"], len(m["rows"]) - 2)

    def test_template_default_next(self):
        m = model(template())
        self.assertEqual(nxt(m), "domain")
        self.assertEqual(m["monthly_cost"], {})
        self.assertNotIn("EUR", status.render_text(m, status.T["en"]))

    def test_nested_parser_matches_pyyaml_on_template(self):
        parsed = status.parse_state(template())
        self.assertEqual(parsed["steps"]["deploy"]["envs"], {"staging": "pending", "prod": "pending"})
        self.assertEqual(parsed["costs"], [])
        self.assertIs(parsed["profile"]["replaces_live_app"], False)
        self.assertEqual(parsed["version"], "2")
        self.assertEqual(parsed["server_defaults"]["provider"], "hetzner")
        try:
            import yaml
        except ImportError:
            return
        y = yaml.safe_load(template())
        a, b = status.build(y), status.build(parsed)
        for key in ("order", "done", "total", "context"):
            self.assertEqual(a[key], b[key])
        self.assertEqual([r["envs"] for r in a["rows"]], [r["envs"] for r in b["rows"]])

    def test_block_style_steps(self):
        text = "project: x\nsteps:\n  domain:\n    status: done\n    owner: claude\n  server:\n    status: pending\n"
        m = status.build(status.parse_state(text))
        self.assertEqual((m["done"], m["total"], m["next"]["step"]), (1, 2, "server"))

    def test_all_done(self):
        m = status.build({"steps": {"domain": {"status": "done"}, "audit": {"status": "skipped"}}})
        self.assertIn("🎉", status.render_text(m, status.T["en"]))

    def test_labels(self):
        for lang in ("en", "tr"):
            self.assertIn("migrate", status.T[lang])
        self.assertEqual((status.T["en"]["migrate"], status.T["tr"]["migrate"]), ("Migration", "Taşıma"))


class Envs(unittest.TestCase):
    def test_done_only_when_all_envs_done_or_skipped(self):
        s = set_step(template(), "deploy", "done", envs={"staging": "done", "prod": "pending"})
        row = {r["step"]: r for r in model(s)["rows"]}["deploy"]
        self.assertEqual(row["status"], "in_progress")  # claimed done, prod pending
        s = set_step(template(), "deploy", "in_progress", envs={"staging": "skipped", "prod": "done"})
        self.assertEqual({r["step"]: r for r in model(s)["rows"]}["deploy"]["status"], "done")
        s = set_step(template(), "deploy", "pending", envs={"staging": "done", "prod": "pending"})
        self.assertEqual({r["step"]: r for r in model(s)["rows"]}["deploy"]["status"], "in_progress")

    def test_text_and_html_show_envs(self):
        s = set_step(template(), "deploy", "in_progress", envs={"staging": "done", "prod": "pending"})
        m = model(s)
        self.assertIn("🔄 Deploy (staging ✅, prod ⏳)", status.render_text(m, status.T["en"]))
        self.assertIn('<i class="env done">staging ✅</i>', status.render_html(m, status.T["en"], "en"))

    def test_missing_envs_old_file(self):
        m = status.build({"steps": {"deploy": {"status": "done"}}})
        self.assertEqual(m["rows"][0]["envs"], {})
        self.assertEqual(m["done"], 1)

    def test_prod_only_layout_hides_staging(self):
        s = template().replace("layout: separate-servers", "layout: prod-only")
        s = set_step(s, "server", "done", envs={"staging": "pending", "prod": "done"})
        row = {r["step"]: r for r in model(s)["rows"]}["server"]
        self.assertEqual(row["envs"], {"prod": "done"})
        self.assertEqual(row["status"], "done")


class Ordering(unittest.TestCase):
    def finish(self, s, names):
        for n in names:
            s = set_step(s, n, "done")
        return s

    def test_default_order(self):
        o = model(template())["order"]
        self.assertLess(o.index("deploy"), o.index("tls"))
        self.assertLess(o.index("tls"), o.index("dns_records"))
        self.assertLess(o.index("dns_records"), o.index("ci_cd"))

    def test_default_next_after_deploy_is_tls(self):
        s = self.finish(template(), ["domain", "nameservers", "environments", "server", "database", "deploy"])
        s = set_step(s, "cluster", "skipped")
        s = set_step(s, "deploy", "done", envs={"staging": "done", "prod": "done"})
        self.assertEqual(nxt(model(s)), "tls")

    def test_no_cloudflare_dns_before_tls(self):
        s = template().replace("dns_provider: cloudflare ", "dns_provider: route53    ")
        s = self.finish(s, ["domain", "nameservers", "environments", "server", "database", "deploy"])
        s = set_step(s, "cluster", "skipped")
        m = model(s)
        self.assertLess(m["order"].index("dns_records"), m["order"].index("tls"))
        self.assertEqual(nxt(m), "dns_records")
        self.assertIn("▶ Next: DNS cutover", status.render_text(m, status.T["en"]))
        self.assertIn("<b>DNS cutover", status.render_html(m, status.T["en"], "en").split('class="next"')[1])

    def test_k8s_order(self):
        s = template().replace("runtime: compose ", "runtime: hetzner-k3s")
        s = self.finish(s, ["domain", "nameservers", "environments"])
        m = model(s)
        o = m["order"]
        self.assertTrue(o.index("cluster") < o.index("database") < o.index("ci_cd") < o.index("dns_records"))
        rows = {r["step"]: r for r in m["rows"]}
        self.assertEqual((rows["server"]["status"], rows["deploy"]["status"]), ("skipped", "skipped"))
        self.assertEqual(nxt(m), "cluster")
        s = self.finish(s, ["cluster", "database"])
        self.assertEqual(nxt(model(s)), "ci_cd")  # not tls / dns_records
        s = self.finish(s, ["ci_cd"])
        self.assertEqual(nxt(model(s)), "tls")  # cluster normally marks it done
        s = self.finish(s, ["tls"])
        self.assertEqual(nxt(model(s)), "dns_records")

    def test_migrate_only_when_replacing_live_app(self):
        base = self.finish(template(), ["domain", "nameservers", "environments", "server", "database", "deploy", "tls"])
        base = set_step(base, "cluster", "skipped")
        m = model(base)
        self.assertEqual({r["step"]: r for r in m["rows"]}["migrate"]["status"], "skipped")
        self.assertEqual(nxt(m), "dns_records")
        s = base.replace("replaces_live_app: false", "replaces_live_app: true")
        m = model(s)
        self.assertEqual({r["step"]: r for r in m["rows"]}["migrate"]["status"], "pending")
        self.assertEqual(nxt(m), "migrate")
        self.assertLess(m["order"].index("migrate"), m["order"].index("dns_records"))

    def test_blocked_user_step_waits_and_is_not_next(self):
        s = self.finish(template(), ["domain"])
        s = set_step(s, "nameservers", "blocked", owner="user", note="change NS at the registrar")
        m = model(s)
        self.assertEqual([r["step"] for r in m["waiting"]], ["nameservers"])
        self.assertNotEqual(nxt(m), "nameservers")
        self.assertEqual(nxt(m), "environments")
        text = status.render_text(m, status.T["en"])
        self.assertIn("Waiting for you", text)
        self.assertIn("change NS at the registrar", text)

    def test_json_uses_same_order(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "golive.yaml")
            Path(p).write_text(template().replace("dns_provider: cloudflare ", "dns_provider: route53    "), encoding="utf-8")
            out = subprocess.run([sys.executable, os.path.join(HERE, "..", "scripts", "status.py"), "--state", p, "--format", "json"],
                                 capture_output=True, text=True).stdout
        data = json.loads(out)
        self.assertEqual(data["order"], model(template().replace("dns_provider: cloudflare ", "dns_provider: route53    "))["order"])
        self.assertLess(data["order"].index("dns_records"), data["order"].index("tls"))


class Costs(unittest.TestCase):
    def with_costs(self, lines):
        return template().replace("costs: []", "costs:\n" + "\n".join("  - " + x for x in lines))

    def test_sum_per_currency(self):
        s = self.with_costs(['{item: "app-prod cx33 fsn1", monthly: 12.5, currency: EUR, step: server}',
                             '{item: "backups", monthly: 30.0, currency: EUR, step: database}',
                             '{item: "mail", monthly: 20, currency: USD, step: mail_send}'])
        m = model(s)
        self.assertEqual(m["monthly_cost"], {"EUR": 42.5, "USD": 20.0})
        self.assertIn("≈ 42.50 EUR + 20.00 USD/month", status.render_text(m, status.T["en"]))
        self.assertIn("≈ 42.50 EUR + 20.00 USD/ay", status.render_html(m, status.T["tr"], "tr"))

    def test_single_currency_header(self):
        s = self.with_costs(['{item: a, monthly: 42.5, currency: EUR, step: server}'])
        self.assertIn("≈ 42.50 EUR/month", status.render_text(model(s), status.T["en"]).split("\n")[1])

    def test_malformed_ignored(self):
        m = status.build({"costs": ["junk", {"item": "x"}, {"monthly": "abc", "currency": "EUR"}, {"monthly": 5},
                                    {"monthly": True, "currency": "EUR"}, {"monthly": -3, "currency": "EUR"},
                                    {"monthly": "7.25", "currency": "eur"}], "steps": {}})
        self.assertEqual(m["monthly_cost"], {"EUR": 7.25})
        self.assertEqual(status.build({"costs": "nope"})["monthly_cost"], {})

    def test_omitted_without_costs(self):
        self.assertNotIn("/month", status.render_text(model(template()), status.T["en"]))
        self.assertNotIn('class="cost"', status.render_html(model(template()), status.T["en"], "en"))


class OldSchema(unittest.TestCase):
    OLD = """version: 1
project: old
domain:
  name: old.com
  dns_provider: cloudflare
runtime: compose
server:
  provider: digitalocean
  name: app-prod
steps:
  domain:        {status: done, owner: claude, note: ""}
  server:        {status: done, owner: claude, note: ""}
  deploy:        {status: pending, owner: claude, note: ""}
  cluster:       {status: pending, owner: claude, note: ""}
  legal_tr:      {status: blocked, owner: user, note: "review"}
"""

    def test_old_file(self):
        m = model(self.OLD)
        self.assertIn("digitalocean", m["context"])
        self.assertEqual([r["step"] for r in m["waiting"]], ["legal"])
        rows = {r["step"]: r for r in m["rows"]}
        self.assertEqual(rows["cluster"]["status"], "skipped")  # compose: cluster does not apply
        self.assertEqual(nxt(m), "deploy")
        self.assertEqual(rows["deploy"]["envs"], {})

    def test_old_legal_tr_name(self):
        m = status.build({"steps": {"legal_tr": {"status": "blocked", "owner": "user", "note": "review"}}})
        self.assertEqual([r["step"] for r in m["waiting"]], ["legal"])


class Hook(unittest.TestCase):
    def test_hook_new_schema_and_fail_open(self):
        hook = os.path.join(HERE, "..", "scripts", "status_hook.py")
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "golive.yaml")
            Path(p).write_text(sample(), encoding="utf-8")
            payload = json.dumps({"tool_name": "Write", "tool_input": {"file_path": p}})
            r = subprocess.run([sys.executable, hook], input=payload, capture_output=True, text=True)
            self.assertEqual(r.returncode, 0)
            ctx = json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"]
            self.assertIn("Deploy (staging ✅, prod ⏳)", ctx)
            self.assertTrue(os.path.exists(os.path.join(d, "golive-status.html")))
            bad = subprocess.run([sys.executable, hook], input="not json", capture_output=True, text=True)
            self.assertEqual((bad.returncode, bad.stdout), (0, ""))


if __name__ == "__main__":
    unittest.main(verbosity=1)
