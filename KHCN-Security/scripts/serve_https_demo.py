"""Start owned loopback Waitress/Caddy processes; Ctrl+C stops only these children."""

import os
import socket
import subprocess
import sys
import time
from contextlib import ExitStack, contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class HTTPSDemoStartupError(RuntimeError):
    """A fixed, non-sensitive explanation safe to display in the terminal."""


def check_ports():
    for port in (8003, 8080, 8443):
        with socket.socket() as listener:
            try:
                listener.bind(("127.0.0.1", port))
            except OSError:
                raise HTTPSDemoStartupError(
                    f"Cannot start: port {port} is already in use. "
                    "Existing processes were not stopped. "
                    "If your HTTPS demo is already running, open https://localhost:8443/ "
                    "instead of starting another instance."
                ) from None


@contextmanager
def running_servers(database=None):
    children = []
    runtime = ROOT / ".runtime"
    if not all(
        (ROOT / name).exists()
        for name in (
            ".env.https",
            ".tools/caddy.exe",
            ".runtime/tls/server-chain.pem",
            "staticfiles",
        )
    ):
        raise HTTPSDemoStartupError(
            "Required HTTPS files are missing. Run setup_https_demo.py and "
            "manage.py collectstatic --noinput --settings=config.settings_https first."
        )
    check_ports()
    try:
        with ExitStack() as stack:
            wsgi_log = stack.enter_context((runtime / "waitress.log").open("ab"))
            proxy_log = stack.enter_context((runtime / "caddy.log").open("ab"))
            flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
            environment = {
                **os.environ,
                "DJANGO_SETTINGS_MODULE": "config.settings_https",
            }
            if database is not None:
                environment["POSTGRES_DB"] = database
            children.append(
                subprocess.Popen(
                    [sys.executable, "-u", "scripts/serve_wsgi.py"],
                    cwd=ROOT,
                    stdout=wsgi_log,
                    stderr=subprocess.STDOUT,
                    env=environment,
                    creationflags=flags,
                )
            )
            children.append(
                subprocess.Popen(
                    [
                        str(ROOT / ".tools/caddy.exe"),
                        "run",
                        "--config",
                        "deploy/Caddyfile",
                        "--adapter",
                        "caddyfile",
                    ],
                    cwd=ROOT,
                    stdout=proxy_log,
                    stderr=subprocess.STDOUT,
                    creationflags=flags,
                )
            )
            yield children
    finally:
        for child in children:
            if child.poll() is None:
                child.terminate()
        for child in children:
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait(timeout=5)


def main():
    with running_servers() as children:
        print(
            "HTTPS demo: https://localhost:8443/ (explicit CA trust required)",
            flush=True,
        )
        print(
            "HTTP redirect: http://localhost:8080/ -> HTTPS. Ctrl+C stops owned servers.",
            flush=True,
        )
        while all(child.poll() is None for child in children):
            time.sleep(0.25)
        raise RuntimeError(
            "HTTPS server stopped; inspect local logs without sharing raw data."
        )


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("HTTPS demo stopped.")
    except HTTPSDemoStartupError as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
    except Exception:
        print(
            "HTTPS demo failed to start/run; no secret values printed.", file=sys.stderr
        )
        sys.exit(1)
