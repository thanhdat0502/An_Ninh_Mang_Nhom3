"""Verify the live local TLS endpoint without disabling certificate checks."""

import hashlib
import json
import shutil
import socket
import ssl
import subprocess
import sys
import warnings
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, HTTPSHandler, ProxyHandler, build_opener

ROOT = Path(__file__).resolve().parents[1]
CA_FILE = ROOT / ".runtime/tls/root-ca.crt"


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def trusted_context():
    # Explicitly trust this demo CA, with hostname validation still required.
    return ssl.create_default_context(cafile=str(CA_FILE))


def handshake(context, hostname="localhost"):
    with socket.create_connection(("127.0.0.1", 8443), timeout=10) as connection:
        with context.wrap_socket(connection, server_hostname=hostname) as stream:
            return {
                "protocol": stream.version(),
                "cipher": stream.cipher()[0],
                "certificate_sha256": hashlib.sha256(
                    stream.getpeercert(binary_form=True)
                ).hexdigest(),
                "certificate": stream.getpeercert(),
            }


def default_trust_status(expected_fingerprint):
    """Observe OS trust without assuming whether the user installed the demo CA."""
    try:
        peer = handshake(ssl.create_default_context())
    except ssl.SSLCertVerificationError as error:
        return {"trusted": False, "verify_code": error.verify_code}
    if peer["certificate_sha256"] != expected_fingerprint:
        raise RuntimeError("Default trust handshake returned a different certificate.")
    return {"trusted": True}


def verify_tls():
    results = {}
    for version in (ssl.TLSVersion.TLSv1_2, ssl.TLSVersion.TLSv1_3):
        context = trusted_context()
        context.minimum_version = context.maximum_version = version
        peer = handshake(context)
        results[peer["protocol"]] = peer
        print(f"PASS verified {peer['protocol']}: {peer['cipher']}")
    trust = default_trust_status(peer["certificate_sha256"])
    results["default trust"] = trust
    print(
        "Default system trust: "
        + ("VERIFIED" if trust["trusted"] else "NOT TRUSTED; explicit demo CA required")
    )
    # Caddy may reject unknown SNI before sending a certificate. Independently
    # verify SAN matching against the same leaf whose live fingerprint is above.
    result = subprocess.run(
        [
            shutil.which("openssl"),
            "verify",
            "-CAfile",
            str(CA_FILE),
            "-verify_hostname",
            "wrong.example",
            str(ROOT / ".runtime/tls/server.crt"),
        ],
        capture_output=True,
    )
    if not result.returncode or b"hostname mismatch" not in result.stderr.lower():
        raise RuntimeError("Hostname mismatch check did not fail as expected.")
    results["certificate hostname mismatch rejected"] = "PASS"
    print("PASS certificate hostname mismatch rejected by OpenSSL verify")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        legacy = trusted_context()
        legacy.minimum_version = ssl.TLSVersion.TLSv1
        legacy.maximum_version = ssl.TLSVersion.TLSv1_1
        # Only a negative handshake probe; never sends credentials or HTTP.
        legacy.set_ciphers("DEFAULT:@SECLEVEL=0")
        try:
            handshake(legacy)
        except ssl.SSLError as error:
            if "PROTOCOL_VERSION" not in error.reason:
                raise RuntimeError(
                    "Legacy probe failed locally, not proven rejected by server."
                ) from None
            results["TLS 1.0/1.1 rejected by server"] = "PASS"
            print("PASS TLS 1.0/1.1 rejected: server protocol_version alert")
        else:
            raise RuntimeError("Legacy TLS unexpectedly accepted.")
    opener = build_opener(ProxyHandler({}), HTTPSHandler(context=trusted_context()))
    for route in ("/health/", "/dang-nhap/", "/static/css/site.css"):
        try:
            response = opener.open("https://localhost:8443" + route, timeout=10)
        except HTTPError as error:
            response = error
        with response:
            if response.status != 200:
                raise RuntimeError("HTTPS route unavailable.")
            results[route] = response.status
            print(f"PASS verified HTTPS {route}: HTTP {response.status}")
    plain = build_opener(ProxyHandler({}), NoRedirect())
    for port, expected in ((8080, 308), (8003, 301)):
        try:
            response = plain.open(f"http://127.0.0.1:{port}/health/", timeout=10)
        except HTTPError as error:
            response = error
        with response:
            if (
                response.status != expected
                or response.headers.get("Location") != "https://localhost:8443/health/"
            ):
                raise RuntimeError("HTTP redirect verification failed.")
            results[f"HTTP {port} redirect"] = expected
            print(f"PASS HTTP {port} -> canonical HTTPS: {expected}")
    directory = ROOT / ".runtime/evidence"
    directory.mkdir(exist_ok=True)
    (directory / "tls-report.json").write_text(
        json.dumps(results, indent=2), encoding="utf-8"
    )
    print(
        "TLS verification PASS; public certificate metadata only, no secrets in evidence."
    )
    return results


if __name__ == "__main__":
    try:
        verify_tls()
    except Exception:
        print(
            "TLS verification FAILED; no sensitive diagnostics displayed.",
            file=sys.stderr,
        )
        sys.exit(1)
