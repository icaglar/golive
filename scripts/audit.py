#!/usr/bin/env python3
"""golive audit: deterministic go-live checks for a domain. Python 3.8+ stdlib only.

DNS is resolved over DNS-over-HTTPS (Cloudflare, then Google), so it works the
same on a laptop, in CI and behind an HTTPS proxy. HTTP checks honour
HTTPS_PROXY. Exit code: 1 if any check FAILs, else 0.

Usage:
  audit.py example.com [--mail-subdomain send] [--dkim-selector resend]
                       [--dns-provider cloudflare] [--server-ip 1.2.3.4]
                       [--ptr-host app.example.com] [--no-mail] [--json]
  --mail-subdomain ''  (or --no-send-subdomain) skips SPF/MX on <sub>.<domain> for providers
                       without a sending subdomain (Google Workspace, Brevo); DKIM is still checked.
  --host-only          audit a subdomain host such as staging.example.com: A/AAAA and web checks
                       only, no NS, www, MX, SPF, DKIM or DMARC checks.
"""
import argparse
import base64
import datetime as dt
import http.client
import ipaddress
import json
import os
import re
import socket
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request

UA = "golive-audit/0.1"
TIMEOUT = 12
DOH = [
    ("https://cloudflare-dns.com/dns-query", {"accept": "application/dns-json"}),
    ("https://dns.google/resolve", {}),
]
RESULTS = []
SERVFAIL_SEEN = set()


def add(status, check, detail=""):
    RESULTS.append({"status": status, "check": check, "detail": detail})


# ---------- DNS over HTTPS ----------

def doh(name, rtype):
    """Return a list of record data strings, [] for NXDOMAIN/no data, None if DoH failed."""
    query = urllib.parse.urlencode({"name": name, "type": rtype})
    for base, headers in DOH:
        req = urllib.request.Request(f"{base}?{query}", headers={"User-Agent": UA, **headers})
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                data = json.load(resp)
        except Exception:
            continue
        type_num = {"A": 1, "NS": 2, "CNAME": 5, "PTR": 12, "MX": 15, "TXT": 16, "AAAA": 28, "DS": 43, "CAA": 257}[rtype]
        status = data.get("Status", 0)
        if status not in (0, 3):  # 0 NOERROR, 3 NXDOMAIN; 2 SERVFAIL is the usual broken-DNSSEC symptom
            if name not in SERVFAIL_SEEN:
                SERVFAIL_SEEN.add(name)
                add("FAIL", f"Resolution of {name}", f"DNS status {status} (SERVFAIL): often a DS record at the registrar that the current DNS provider does not sign for")
            return []
        out = []
        for ans in data.get("Answer", []) or []:
            if ans.get("type") == type_num:
                out.append(str(ans.get("data", "")).strip())
        return out
    return None


def txt(name):
    """TXT records with their character-strings joined (long DKIM keys are split)."""
    records = doh(name, "TXT")
    if records is None:
        return None
    joined = []
    for r in records:
        parts = re.findall(r'"((?:[^"\\]|\\.)*)"', r)
        joined.append("".join(parts) if parts else r)
    return joined


# ---------- HTTP ----------

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def fetch(url, follow=True):
    """Return (status, headers, final_url) or raise."""
    handlers = [] if follow else [NoRedirect()]
    opener = urllib.request.build_opener(*handlers)
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with opener.open(req, timeout=TIMEOUT) as resp:
            return resp.status, resp.headers, resp.geturl()
    except urllib.error.HTTPError as e:
        return e.code, e.headers, url


def cert_days_left(host):
    """Days until the served certificate expires. Tunnels through HTTPS_PROXY if set."""
    ctx = ssl.create_default_context()
    proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
    no_proxy = os.environ.get("NO_PROXY") or os.environ.get("no_proxy") or ""
    if proxy and not any(host.endswith(p.strip().lstrip(".")) for p in no_proxy.split(",") if p.strip()):
        p = urllib.parse.urlparse(proxy)
        conn = http.client.HTTPSConnection(p.hostname, p.port or 8080, context=ctx, timeout=TIMEOUT)
        headers = {}
        if p.username:
            token = base64.b64encode(f"{urllib.parse.unquote(p.username)}:{urllib.parse.unquote(p.password or '')}".encode()).decode()
            headers["Proxy-Authorization"] = f"Basic {token}"
        conn.set_tunnel(host, 443, headers=headers)
        conn.connect()
        cert = conn.sock.getpeercert()
        conn.close()
    else:
        with socket.create_connection((host, 443), timeout=TIMEOUT) as sock:
            with ctx.wrap_socket(sock, server_hostname=host) as tls:
                cert = tls.getpeercert()
    expires = dt.datetime.strptime(cert["notAfter"], "%b %d %H:%M:%S %Y %Z").replace(tzinfo=dt.timezone.utc)
    issuer = dict(x[0] for x in cert.get("issuer", ()))
    return (expires - dt.datetime.now(dt.timezone.utc)).days, issuer.get("organizationName", "?")


# ---------- checks ----------

def check_dns(domain, dns_provider):
    ns = doh(domain, "NS")
    if ns is None:
        add("FAIL", "DNS lookups", "DNS-over-HTTPS unreachable; cannot audit DNS")
        return False
    if not ns:
        add("FAIL", "NS", f"no nameservers for {domain} (not registered or not delegated)")
    elif dns_provider == "cloudflare":
        on_cf = all(n.rstrip(".").endswith("ns.cloudflare.com") for n in ns)
        add("PASS" if on_cf else "FAIL", "NS on Cloudflare", ", ".join(n.rstrip(".") for n in ns))
    else:
        add("INFO", "NS", ", ".join(n.rstrip(".") for n in ns))

    a = doh(domain, "A") or []
    aaaa = doh(domain, "AAAA") or []
    add("PASS" if a else "FAIL", "A (apex)", ", ".join(a) or "missing")
    add("PASS" if aaaa else "WARN", "AAAA (apex)", ", ".join(aaaa) or "missing (IPv6 visitors fall back to IPv4)")
    www = (doh(f"www.{domain}", "CNAME") or []) + (doh(f"www.{domain}", "A") or [])
    add("PASS" if www else "WARN", "www", ", ".join(www) or "missing (www.example.com will not resolve)")
    caa = doh(domain, "CAA") or []
    add("INFO", "CAA", ", ".join(caa) or "none (any CA may issue; fine for most sites)")
    ds = doh(domain, "DS") or []
    add("INFO", "DNSSEC (DS)", "DS record present: the DNS provider must sign the zone" if ds else "no DS record (DNSSEC off)")
    return True


def spf_records(name):
    records = txt(name) or []
    return [r for r in records if r.lower().startswith("v=spf1")]


def check_host_dns(host):
    """DNS for a subdomain host: address records only (NS and mail belong to the apex)."""
    raw_a = doh(host, "A")
    if raw_a is None:
        add("FAIL", "DNS lookups", "DNS-over-HTTPS unreachable; cannot audit DNS")
        return False
    a = raw_a + (doh(host, "CNAME") or [])
    aaaa = doh(host, "AAAA") or []
    add("PASS" if (a or aaaa) else "FAIL", f"A/CNAME ({host})", ", ".join(a + aaaa) or "missing")
    return True


def check_mail(domain, sub, selector):
    mx = doh(domain, "MX") or []
    add("PASS" if mx else "WARN", "MX (inbound)", ", ".join(mx) or "missing: nobody can mail info@ or receive DMARC reports")

    apex_spf = spf_records(domain)
    if len(apex_spf) > 1:
        add("FAIL", "SPF (apex)", f"{len(apex_spf)} SPF records; must be exactly one (permerror otherwise)")
    elif apex_spf:
        bad = "+all" in apex_spf[0]
        add("FAIL" if bad else "PASS", "SPF (apex)", apex_spf[0])
    else:
        add("WARN" if mx else "INFO", "SPF (apex)", "none (add one if mail is sent or routed on the apex)")

    if sub:
        send_host = f"{sub}.{domain}"
        send_spf = spf_records(send_host)
        if len(send_spf) > 1:
            add("FAIL", f"SPF ({send_host})", f"{len(send_spf)} SPF records; must be exactly one")
        else:
            add("PASS" if send_spf else "FAIL", f"SPF ({send_host})", send_spf[0] if send_spf else "missing: provider's SPF record not published")
        send_mx = doh(send_host, "MX") or []
        add("PASS" if send_mx else "WARN", f"MX ({send_host})", ", ".join(send_mx) or "missing: bounces and complaints are not returned")
    else:
        add("INFO", "Sending subdomain", "skipped (provider sends from the apex domain; SPF on the apex is checked above)")

    dkim_host = f"{selector}._domainkey.{domain}"
    dkim = [r for r in (txt(dkim_host) or []) if "p=" in r]
    if not dkim:
        dkim = doh(dkim_host, "CNAME") or []
    add("PASS" if dkim else "FAIL", f"DKIM ({selector})", (dkim[0][:70] + "…") if dkim else f"missing at {dkim_host}")

    dmarc = [r for r in (txt(f"_dmarc.{domain}") or []) if r.lower().startswith("v=dmarc1")]
    if len(dmarc) > 1:
        add("FAIL", "DMARC", "more than one DMARC record")
    elif not dmarc:
        add("FAIL", "DMARC", "missing at _dmarc (Gmail and Yahoo require it for bulk senders)")
    else:
        tags = {}
        for tag in dmarc[0].split(";"):
            if "=" in tag:
                key, value = tag.split("=", 1)
                tags[key.strip().lower()] = value.strip()
        policy = tags.get("p", "").lower()
        if policy in ("quarantine", "reject"):
            add("PASS", "DMARC", dmarc[0])
        else:
            add("WARN", "DMARC", f"p={policy or '?'}: monitoring only; move to quarantine once reports are clean")
        if "rua" not in tags:
            add("WARN", "DMARC reports", "no rua= address; you will not see who sends as your domain")


def check_web(domain):
    try:
        status, headers, final = fetch(f"https://{domain}/")
        ok = 200 <= status < 400
        add("PASS" if ok else "FAIL", "HTTPS", f"{status} {final}")
    except Exception as e:
        add("FAIL", "HTTPS", f"unreachable: {e.__class__.__name__}: {e}")
        return

    try:
        status, h, _ = fetch(f"http://{domain}/", follow=False)
        location = h.get("Location", "") if h else ""
        good = status in (301, 302, 307, 308) and location.startswith("https://")
        add("PASS" if good else "FAIL", "HTTP → HTTPS", f"{status} {location}".strip())
    except Exception as e:
        add("WARN", "HTTP → HTTPS", f"could not test: {e.__class__.__name__}")

    hsts = headers.get("Strict-Transport-Security", "")
    if not hsts:
        add("WARN", "HSTS", "missing")
    else:
        try:
            max_age = int(hsts.lower().split("max-age=")[1].split(";")[0].strip())
        except Exception:
            max_age = 0
        add("PASS" if max_age >= 15552000 else "WARN", "HSTS", hsts)

    missing = []
    if headers.get("X-Content-Type-Options", "").lower() != "nosniff":
        missing.append("X-Content-Type-Options")
    if not headers.get("Referrer-Policy"):
        missing.append("Referrer-Policy")
    csp = headers.get("Content-Security-Policy", "")
    if not headers.get("X-Frame-Options") and "frame-ancestors" not in csp:
        missing.append("X-Frame-Options or CSP frame-ancestors")
    add("WARN" if missing else "PASS", "Security headers", ("missing: " + ", ".join(missing)) if missing else "ok")

    try:
        days, issuer = cert_days_left(domain)
        status = "FAIL" if days < 7 else "WARN" if days < 21 else "PASS"
        add(status, "TLS certificate", f"{days} days left, issuer {issuer}")
    except ssl.SSLCertVerificationError as e:
        add("FAIL", "TLS certificate", f"not valid: {e.verify_message}")
    except Exception as e:
        add("WARN", "TLS certificate", f"could not read: {e.__class__.__name__}: {e}")

    for path, level in (("/robots.txt", "WARN"), ("/sitemap.xml", "INFO"), ("/.well-known/security.txt", "INFO")):
        try:
            status, _, _ = fetch(f"https://{domain}{path}")
            add("PASS" if status == 200 else level, path, str(status))
        except Exception as e:
            add(level, path, e.__class__.__name__)


def check_ptr(ip, expected):
    try:
        iface = ipaddress.ip_interface(ip)
    except ValueError:
        add("FAIL", "PTR", f"invalid IP {ip}")
        return
    addr = iface.ip
    if addr.version == 6 and iface.network.prefixlen < 128 and addr == iface.network.network_address:
        addr = addr + 1  # Hetzner reports the /64; the server itself uses <prefix>::1
    ip, rev = str(addr), addr.reverse_pointer
    ptr = [p.rstrip(".") for p in (doh(rev, "PTR") or [])]
    if expected:
        add("PASS" if expected.rstrip(".") in ptr else "WARN", f"PTR {ip}", ", ".join(ptr) or "none")
    else:
        add("INFO", f"PTR {ip}", ", ".join(ptr) or "none")


def main():
    ap = argparse.ArgumentParser(description="golive deterministic go-live audit")
    ap.add_argument("domain")
    ap.add_argument("--mail-subdomain", default="send", help="sending subdomain used by the mail provider (Resend: send)")
    ap.add_argument("--no-send-subdomain", action="store_true", help="provider has no sending subdomain: skip SPF/MX on <sub>.<domain> (same as --mail-subdomain '')")
    ap.add_argument("--host-only", action="store_true", help="audit a subdomain host (e.g. staging.example.com): address records and web checks only, no NS/www/mail")
    ap.add_argument("--dkim-selector", default="resend")
    ap.add_argument("--dns-provider", default="cloudflare")
    ap.add_argument("--server-ip", action="append", default=[], help="check reverse DNS of this IP (repeatable)")
    ap.add_argument("--ptr-host", help="expected PTR hostname for --server-ip")
    ap.add_argument("--no-mail", action="store_true", help="skip mail checks")
    ap.add_argument("--no-web", action="store_true", help="skip HTTP/TLS checks")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    domain = args.domain.strip().lower().rstrip(".")
    if domain.startswith("http"):
        domain = urllib.parse.urlparse(domain).hostname or domain

    sub = "" if args.no_send_subdomain else (args.mail_subdomain or "").strip().strip(".")
    ok = check_host_dns(domain) if args.host_only else check_dns(domain, args.dns_provider)
    if ok:
        if not args.no_mail and not args.host_only:
            check_mail(domain, sub, args.dkim_selector)
        for ip in args.server_ip:
            check_ptr(ip, args.ptr_host)
    if not args.no_web:
        check_web(domain)

    if args.json:
        print(json.dumps({"domain": domain, "results": RESULTS}, ensure_ascii=False, indent=2))
    else:
        icons = {"PASS": "✅", "WARN": "⚠️ ", "FAIL": "❌", "INFO": "ℹ️ "}
        width = max(len(r["check"]) for r in RESULTS) if RESULTS else 10
        print(f"golive audit: {domain}\n")
        for r in RESULTS:
            print(f"{icons[r['status']]} {r['check']:<{width}}  {r['detail']}")
        counts = {k: sum(1 for r in RESULTS if r["status"] == k) for k in ("PASS", "WARN", "FAIL")}
        print(f"\n{counts['PASS']} pass, {counts['WARN']} warn, {counts['FAIL']} fail")
    sys.exit(1 if any(r["status"] == "FAIL" for r in RESULTS) else 0)


if __name__ == "__main__":
    main()
