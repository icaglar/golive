#!/usr/bin/env python3
"""Tests for scripts/audit.py with DNS and HTTP mocked. Run: python3 tests/test_audit.py"""
import os
import sys
import unittest
from email.message import Message

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import audit  # noqa: E402

ORIGINAL_DOH = audit.doh

GOOD_DNS = {
    ("example.com", "NS"): ["ada.ns.cloudflare.com.", "bob.ns.cloudflare.com."],
    ("example.com", "A"): ["104.21.1.1"],
    ("example.com", "AAAA"): ["2606:4700::1"],
    ("www.example.com", "CNAME"): ["example.com."],
    ("example.com", "MX"): ["10 route1.mx.cloudflare.net."],
    ("example.com", "TXT"): ['"v=spf1 include:_spf.mx.cloudflare.net ~all"', '"google-site-verification=x"'],
    ("send.example.com", "TXT"): ['"v=spf1 include:amazonses.com ~all"'],
    ("send.example.com", "MX"): ["10 feedback-smtp.eu-west-1.amazonses.com."],
    ("resend._domainkey.example.com", "TXT"): ['"p=MIGfMA0GCSqGSIb3DQEB" "AQUAA4GNADCBiQKBgQC"'],
    ("_dmarc.example.com", "TXT"): ['"v=DMARC1; p=quarantine; rua=mailto:dmarc@example.com"'],
    ("4.3.2.1.in-addr.arpa", "PTR"): ["app.example.com."],
}


def headers(**kw):
    m = Message()
    for k, v in kw.items():
        m[k.replace("_", "-")] = v
    return m


GOOD_HEADERS = headers(
    Strict_Transport_Security="max-age=31536000",
    X_Content_Type_Options="nosniff",
    Referrer_Policy="strict-origin-when-cross-origin",
    X_Frame_Options="DENY",
)


class AuditTest(unittest.TestCase):
    def setUp(self):
        audit.RESULTS.clear()
        audit.SERVFAIL_SEEN.clear()
        self.dns = dict(GOOD_DNS)
        audit.doh = lambda name, rtype: self.dns.get((name, rtype), [])
        self.https_headers = GOOD_HEADERS
        self.http_redirect = (301, headers(Location="https://example.com/"), "http://example.com/")

        def fetch(url, follow=True):
            if url.startswith("http://"):
                return self.http_redirect
            if url.endswith("/sitemap.xml") or url.endswith("security.txt"):
                return 404, headers(), url
            return 200, self.https_headers, url

        audit.fetch = fetch
        audit.cert_days_left = lambda host: (80, "Google Trust Services")

    def status(self, check):
        for r in audit.RESULTS:
            if r["check"] == check:
                return r["status"]
        raise KeyError(check)

    def run_all(self):
        audit.check_dns("example.com", "cloudflare")
        audit.check_mail("example.com", "send", "resend")
        audit.check_ptr("1.2.3.4", "app.example.com")
        audit.check_web("example.com")

    def test_good_domain_has_no_fail(self):
        self.run_all()
        fails = [r for r in audit.RESULTS if r["status"] == "FAIL"]
        self.assertEqual(fails, [])
        self.assertEqual(self.status("DKIM (resend)"), "PASS")
        self.assertEqual(self.status("DMARC"), "PASS")
        self.assertEqual(self.status("PTR 1.2.3.4"), "PASS")
        self.assertEqual(self.status("TLS certificate"), "PASS")

    def test_two_spf_records_fail(self):
        self.dns[("example.com", "TXT")] = ['"v=spf1 include:a ~all"', '"v=spf1 include:b ~all"']
        audit.check_mail("example.com", "send", "resend")
        self.assertEqual(self.status("SPF (apex)"), "FAIL")

    def test_plus_all_fails(self):
        self.dns[("example.com", "TXT")] = ['"v=spf1 +all"']
        audit.check_mail("example.com", "send", "resend")
        self.assertEqual(self.status("SPF (apex)"), "FAIL")

    def test_missing_dkim_and_dmarc_fail(self):
        del self.dns[("resend._domainkey.example.com", "TXT")]
        del self.dns[("_dmarc.example.com", "TXT")]
        audit.check_mail("example.com", "send", "resend")
        self.assertEqual(self.status("DKIM (resend)"), "FAIL")
        self.assertEqual(self.status("DMARC"), "FAIL")

    def test_dmarc_none_warns(self):
        self.dns[("_dmarc.example.com", "TXT")] = ['"v=DMARC1; p=none"']
        audit.check_mail("example.com", "send", "resend")
        self.assertEqual(self.status("DMARC"), "WARN")
        self.assertEqual(self.status("DMARC reports"), "WARN")

    def test_split_dkim_is_joined(self):
        self.assertEqual(audit.txt.__name__, "txt")
        joined = audit.txt("resend._domainkey.example.com")
        self.assertEqual(joined, ["p=MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQC"])

    def test_ns_not_cloudflare_fails(self):
        self.dns[("example.com", "NS")] = ["ns1.porkbun.com."]
        audit.check_dns("example.com", "cloudflare")
        self.assertEqual(self.status("NS on Cloudflare"), "FAIL")

    def test_no_redirect_and_no_hsts(self):
        self.http_redirect = (200, headers(), "http://example.com/")
        self.https_headers = headers()
        audit.check_web("example.com")
        self.assertEqual(self.status("HTTP → HTTPS"), "FAIL")
        self.assertEqual(self.status("HSTS"), "WARN")
        self.assertEqual(self.status("Security headers"), "WARN")

    def test_expiring_cert_fails(self):
        audit.cert_days_left = lambda host: (3, "R11")
        audit.check_web("example.com")
        self.assertEqual(self.status("TLS certificate"), "FAIL")

    def test_dmarc_with_spaces(self):
        self.dns[("_dmarc.example.com", "TXT")] = ['"v=DMARC1; p = reject ; rua = mailto:d@example.com"']
        audit.check_mail("example.com", "send", "resend")
        self.assertEqual(self.status("DMARC"), "PASS")

    def test_ipv6_network_uses_host_one(self):
        self.dns[("1.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.8.b.d.0.1.0.0.2.ip6.arpa", "PTR")] = ["app.example.com."]
        audit.check_ptr("2001:db8::/64", "app.example.com")
        self.assertEqual(self.status("PTR 2001:db8::1"), "PASS")

    def test_servfail_reported(self):
        import io
        import json as _json
        import urllib.request

        class Resp(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        real = urllib.request.urlopen
        urllib.request.urlopen = lambda req, timeout=None: Resp(_json.dumps({"Status": 2}).encode())
        try:
            self.assertEqual(ORIGINAL_DOH("example.com", "NS"), [])
            self.assertEqual(ORIGINAL_DOH("example.com", "A"), [])
        finally:
            urllib.request.urlopen = real
        servfails = [r for r in audit.RESULTS if r["check"] == "Resolution of example.com"]
        self.assertEqual(len(servfails), 1)
        self.assertEqual(servfails[0]["status"], "FAIL")

    def test_no_send_subdomain_skips_spf_mx_but_checks_dkim(self):
        for k in [("send.example.com", "TXT"), ("send.example.com", "MX")]:
            del self.dns[k]
        audit.check_mail("example.com", "", "resend")
        self.assertEqual(self.status("Sending subdomain"), "INFO")
        self.assertEqual(self.status("DKIM (resend)"), "PASS")
        self.assertFalse([r for r in audit.RESULTS if r["check"].startswith("SPF (send")])
        self.assertEqual([r for r in audit.RESULTS if r["status"] == "FAIL"], [])
        del self.dns[("resend._domainkey.example.com", "TXT")]
        audit.RESULTS.clear()
        audit.check_mail("example.com", "", "resend")
        self.assertEqual(self.status("DKIM (resend)"), "FAIL")

    def test_host_only_has_no_ns_or_mail_checks(self):
        self.dns[("staging.example.com", "A")] = ["203.0.113.5"]
        self.assertTrue(audit.check_host_dns("staging.example.com"))
        self.assertEqual(self.status("A/CNAME (staging.example.com)"), "PASS")
        self.assertEqual([r["check"] for r in audit.RESULTS if r["check"].startswith(("NS", "MX", "SPF"))], [])

    def test_host_only_missing_record_fails(self):
        audit.check_host_dns("staging.example.com")
        self.assertEqual(self.status("A/CNAME (staging.example.com)"), "FAIL")

    def test_cli_host_only_and_no_send_subdomain(self):
        import io
        import contextlib
        self.dns[("staging.example.com", "A")] = ["203.0.113.5"]
        argv = sys.argv
        sys.argv = ["audit.py", "staging.example.com", "--host-only", "--no-web", "--json"]
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf), self.assertRaises(SystemExit) as cm:
                audit.main()
        finally:
            sys.argv = argv
        self.assertEqual(cm.exception.code, 0)
        self.assertNotIn("NS", buf.getvalue().replace("DNS", ""))

    def test_doh_down(self):
        audit.doh = lambda name, rtype: None
        self.assertFalse(audit.check_dns("example.com", "cloudflare"))
        self.assertEqual(self.status("DNS lookups"), "FAIL")


if __name__ == "__main__":
    unittest.main(verbosity=1)
