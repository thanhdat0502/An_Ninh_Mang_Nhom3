"""Prepare a private local CA, TLS leaf, HTTPS secrets and portable Caddy.

Does not install a CA into Windows/browser trust, edit .env, or open firewall
ports. Uses the existing OpenSSL; private material stays under ignored paths.
"""

import hashlib
import io
import os
import secrets
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
CADDY_VERSION = "2.11.9"
CADDY_ARCHIVE_SHA256 = (
    "ad93112d335ee687100c4c9f11bced16ca590377976b7fe7883882b9e797e472"
)


def run_openssl(*arguments):
    result = subprocess.run(
        [shutil.which("openssl"), *map(str, arguments)],
        cwd=ROOT,
        capture_output=True,
    )
    if result.returncode:
        raise RuntimeError("OpenSSL không hoàn tất; không in nội dung key/diagnostic.")


def protect_runtime(directory):
    if os.name == "nt":
        principal = subprocess.check_output(["whoami"], text=True).strip()
        result = subprocess.run(
            [
                "icacls",
                str(directory),
                "/inheritance:r",
                "/grant:r",
                f"{principal}:(OI)(CI)F",
                "*S-1-5-18:(OI)(CI)F",
            ],
            capture_output=True,
        )
        if result.returncode:
            raise RuntimeError("Không đặt được ACL thư mục chứa key demo.")
    else:
        directory.chmod(0o700)


def prepare_caddy():
    destination = ROOT / ".tools" / "caddy.exe"
    if destination.exists():
        result = subprocess.run(
            [destination, "version"], capture_output=True, text=True
        )
        if result.returncode or not result.stdout.startswith(f"v{CADDY_VERSION} "):
            raise RuntimeError(
                "Caddy cục bộ không khớp phiên bản đã pin; không ghi đè."
            )
        return
    url = (
        f"https://github.com/caddyserver/caddy/releases/download/v{CADDY_VERSION}/"
        f"caddy_{CADDY_VERSION}_windows_amd64.zip"
    )
    request = Request(url, headers={"User-Agent": "KHCN-Security-local-demo-setup"})
    with urlopen(request, timeout=120) as response:
        archive = response.read(64 * 1024 * 1024)
    if hashlib.sha256(archive).hexdigest() != CADDY_ARCHIVE_SHA256:
        raise RuntimeError("Checksum Caddy không khớp; không chạy binary tải về.")
    destination.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
        # Read only this member; never extract arbitrary archive paths.
        binary = bundle.read("caddy.exe")
    destination.write_bytes(binary)
    print(f"PASS portable Caddy {CADDY_VERSION}: official release SHA-256 verified.")


def prepare_tls():
    directory = ROOT / ".runtime" / "tls"
    directory.parent.mkdir(exist_ok=True)
    protect_runtime(directory.parent)
    directory.mkdir(exist_ok=True)
    root_key, root_cert = directory / "root-ca.key", directory / "root-ca.crt"
    leaf_key, leaf_cert = directory / "server.key", directory / "server.crt"
    chain = directory / "server-chain.pem"
    material = (root_key, root_cert, leaf_key, leaf_cert, chain)
    if all(path.exists() for path in material):
        run_openssl(
            "verify", "-CAfile", root_cert, "-verify_hostname", "localhost", leaf_cert
        )
        run_openssl("x509", "-in", leaf_cert, "-checkend", "86400", "-noout")
        print("PASS existing demo certificate: chain/hostname/validity checked.")
        return
    if any(path.exists() for path in material):
        raise RuntimeError("Bộ key/chứng chỉ chưa đủ; không tự ghi đè file có sẵn.")
    # Do not depend on a global openssl.cnf (some Windows builds have none).
    config = directory / "openssl.cnf"
    config.write_text("[req]\ndistinguished_name=dn\n[dn]\n", encoding="ascii")
    run_openssl(
        "req",
        "-config",
        config,
        "-x509",
        "-newkey",
        "rsa:3072",
        "-noenc",
        "-sha256",
        "-days",
        "365",
        "-keyout",
        root_key,
        "-out",
        root_cert,
        "-subj",
        "/CN=KHCN Local Demo Root CA",
        "-addext",
        "basicConstraints=critical,CA:TRUE,pathlen:0",
        "-addext",
        "keyUsage=critical,keyCertSign,cRLSign",
    )
    csr = directory / "server.csr"
    run_openssl(
        "req",
        "-config",
        config,
        "-new",
        "-newkey",
        "rsa:3072",
        "-noenc",
        "-sha256",
        "-keyout",
        leaf_key,
        "-out",
        csr,
        "-subj",
        "/CN=localhost",
    )
    extensions = directory / "server-extensions.cnf"
    extensions.write_text(
        "basicConstraints=critical,CA:FALSE\n"
        "keyUsage=critical,digitalSignature,keyEncipherment\n"
        "extendedKeyUsage=serverAuth\n"
        "subjectAltName=DNS:localhost,IP:127.0.0.1\n",
        encoding="ascii",
    )
    run_openssl(
        "x509",
        "-req",
        "-in",
        csr,
        "-CA",
        root_cert,
        "-CAkey",
        root_key,
        "-CAcreateserial",
        "-out",
        leaf_cert,
        "-days",
        "30",
        "-sha256",
        "-extfile",
        extensions,
    )
    chain.write_bytes(leaf_cert.read_bytes() + root_cert.read_bytes())
    run_openssl(
        "verify", "-CAfile", root_cert, "-verify_hostname", "localhost", leaf_cert
    )
    if os.name != "nt":
        for key in (root_key, leaf_key):
            key.chmod(0o600)
    print(
        "PASS local CA and 30-day localhost certificate generated; Windows trust unchanged."
    )


def prepare_secrets():
    destination = ROOT / ".env.https"
    if destination.exists():
        print("HTTPS environment already exists; no values changed or displayed.")
        return
    # Env file inherits the project ACL; private runtime keys have a tighter ACL.
    with destination.open("x", encoding="utf-8") as output:
        output.write("# Local HTTPS demo only. Never commit or display this file.\n")
        for name in ("KHCN_HTTPS_SECRET_KEY", "KHCN_HTTPS_JWT_SIGNING_KEY"):
            output.write(f"{name}={secrets.token_urlsafe(64)}\n")
    if os.name == "nt":
        principal = subprocess.check_output(["whoami"], text=True).strip()
        result = subprocess.run(
            [
                "icacls",
                str(destination),
                "/inheritance:r",
                "/grant:r",
                f"{principal}:F",
                "*S-1-5-18:F",
            ],
            capture_output=True,
        )
        if result.returncode:
            raise RuntimeError("Không đặt được ACL cho .env.https.")
    else:
        destination.chmod(0o600)
    print("PASS independent HTTPS secrets generated; values not displayed.")


def main():
    if os.name != "nt" or not shutil.which("openssl"):
        raise RuntimeError("Script demo này cần Windows và OpenSSL đã cài.")
    prepare_tls()
    prepare_secrets()
    prepare_caddy()
    print("Setup complete. No CA trust/system tool/firewall setting changed.")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        print(
            "HTTPS setup failed. No key, password or secret values printed.",
            file=sys.stderr,
        )
        sys.exit(1)
