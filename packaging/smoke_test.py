"""Smoke-test a frozen OpenWarframe build (used by CI and the release workflow).

    uv run python packaging/smoke_test.py dist/OpenWarframe/openwarframe-cli.exe
    uv run python packaging/smoke_test.py dist/OpenWarframe.app/Contents/MacOS/openwarframe-cli

Checks that the CLI starts, that the bundled knowledge base and web page are inside the
build, and that the app server answers. It never touches the network or the real data
folder: everything runs against a fresh temporary home.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

PORT = 8765


def run(cli: Path, *args: str, env: dict) -> str:
    out = subprocess.run([str(cli), *args], capture_output=True, text=True, env=env, timeout=120, check=False)
    if out.returncode != 0:
        raise SystemExit(
            f"`{cli.name} {' '.join(args)}` failed ({out.returncode}):\n{out.stdout}\n{out.stderr}"
        )
    return out.stdout


def get(path: str) -> tuple[int, bytes]:
    with urllib.request.urlopen(f"http://127.0.0.1:{PORT}{path}", timeout=3) as r:
        return r.status, r.read()


def main() -> None:
    cli = Path(sys.argv[1]).resolve()
    if not cli.exists():
        raise SystemExit(f"no CLI at {cli}")
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as home:
        env = {**os.environ, "OPENWARFRAME_HOME": home, "PYTHONIOENCODING": "utf-8"}
        run(cli, "--help", env=env)
        print("version:", run(cli, "version", env=env).strip())
        # the knowledge base ships inside the build (kb_data); a missing data file fails here
        print(run(cli, "selfcheck", env=env).strip())

        server = subprocess.Popen(
            [str(cli), "gui", "--no-window", "--port", str(PORT)],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            for _ in range(60):
                time.sleep(1)
                try:
                    if json.loads(get("/api/ping")[1]).get("ok"):
                        break
                except OSError:
                    continue
            else:
                raise SystemExit("the app server did not answer /api/ping within 60 s")
            status, page = get("/")
            if status != 200 or b"OpenWarframe" not in page:
                raise SystemExit("the app page was not served")
            status, mini = get("/mini")
            if status != 200:
                raise SystemExit("the reward pop-out page was not served")
            print("app server: ok")
        finally:
            server.terminate()
            try:
                server.wait(timeout=10)
            except subprocess.TimeoutExpired:
                server.kill()
    print("smoke test passed")


if __name__ == "__main__":
    main()
