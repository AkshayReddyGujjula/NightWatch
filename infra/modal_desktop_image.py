"""NightWatch Track B — pinned desktop world image (plan §11.6, §12.2).

One image, used by every A/B/C candidate Sandbox and by the CUA-in-Modal
gate. It contains:

* X11 (Xvfb + Openbox), D-Bus and AT-SPI (`dbus`, `dbus-x11`, `at-spi2-core`);
* Google Chrome installed as a **root-owned OS package** (`.deb`), which is the
  product CUA documents as validated on Linux X11 — Chromium on Linux X11 is
  descriptor-backed but not yet product-validated (cua.ai platform docs,
  2026-09-19). Switch ``NW_BROWSER`` to ``chromium`` only if a decision
  explicitly changes this;
* CUA Driver ``0.28.2`` from the tag-pinned GitHub release, SHA-256 verified at
  build time against the checksum published in that release;
* two non-root identities (``nightwatch_app``, ``nightwatch_controller``) and
  **no secrets of any kind**.

Version evidence is written to ``/opt/nightwatch/versions.txt`` during the
build; the T+0:50 gate records it and the receipt copies it.

Dev-only check (ephemeral, never deployed):  uv run modal run infra/modal_desktop_image.py
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import modal

# --- pinned versions ---------------------------------------------------------

CUA_DRIVER_VERSION = "0.28.2"
# From the release body of cua-driver-rs-v0.28.2 (GitHub API, 2026-09-19).
CUA_DRIVER_ASSET = f"cua-driver-rs-{CUA_DRIVER_VERSION}-linux-x86_64-binary.tar.gz"
CUA_DRIVER_SHA256 = "a1d99fd04bb4927ef5ffdbe60eb91ed8b51a2bab60e10fc604a75bd59ce69c3e"
CUA_DRIVER_URL = (
    f"https://github.com/trycua/cua/releases/download/"
    f"cua-driver-rs-v{CUA_DRIVER_VERSION}/{CUA_DRIVER_ASSET}"
)

CHROME_DEB_URL = "https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb"

APP_USER = "nightwatch_app"
CTL_USER = "nightwatch_controller"
APP_UID = 2001
CTL_UID = 2002

_BASE_PACKAGES = (
    # X11 desktop
    "xvfb",
    "openbox",
    "xauth",
    "x11-utils",
    # D-Bus / accessibility (CUA Driver Linux requirements)
    "dbus",
    "dbus-x11",
    "at-spi2-core",
    "libxi6",
    # process management and diagnostics
    "util-linux",
    "procps",
    "iproute2",
    "curl",
    "ca-certificates",
    # fonts (Chrome depends on fonts-liberation; keep text rendering sane)
    "fonts-liberation",
    "fonts-dejavu-core",
)

_IMAGE_DIR = Path(__file__).parent
_REMOTE_DIR = "/opt/nightwatch"

DESKTOP_IMAGE = (
    modal.Image.debian_slim(python_version="3.12")
    .apt_install(*_BASE_PACKAGES)
    .run_commands(
        # --- Google Chrome as a root-owned system package --------------------
        f"curl -fsSL -o /tmp/google-chrome.deb {CHROME_DEB_URL}",
        "apt-get install -y /tmp/google-chrome.deb",
        "rm -f /tmp/google-chrome.deb",
        # --- CUA Driver, pinned and checksum-verified ------------------------
        f"curl -fsSL -o /tmp/cua-driver.tgz {CUA_DRIVER_URL}",
        f"echo '{CUA_DRIVER_SHA256}  /tmp/cua-driver.tgz' | sha256sum -c -",
        f"mkdir -p /opt/cua-driver/{CUA_DRIVER_VERSION}",
        f"tar -xzf /tmp/cua-driver.tgz -C /opt/cua-driver/{CUA_DRIVER_VERSION}",
        "CUA_BIN=\"$(find /opt/cua-driver -maxdepth 3 -type f -name cua-driver | head -n1)\"",
        '[ -n "$CUA_BIN" ] || { echo "cua-driver binary not found in release archive"; exit 1; }',
        'ln -s "$CUA_BIN" /usr/local/bin/cua-driver',
        "rm -f /tmp/cua-driver.tgz",
        # --- two non-root identities, root-owned homes -----------------------
        f"groupadd --gid {APP_UID} {APP_USER}",
        f"useradd --uid {APP_UID} --gid {APP_UID} --create-home --shell /bin/bash {APP_USER}",
        f"groupadd --gid {CTL_UID} {CTL_USER}",
        f"useradd --uid {CTL_UID} --gid {CTL_UID} --create-home --shell /bin/bash {CTL_USER}",
        f"chmod 700 /home/{APP_USER} /home/{CTL_USER}",
        # --- recorded versions (evidence for the receipt) --------------------
        "mkdir -p /opt/nightwatch",
        "{ echo \"browser=$(google-chrome --version)\"; "
        "echo \"cua_driver=$(cua-driver --version)\"; "
        "echo \"base_image=debian_slim python3.12\"; } > /opt/nightwatch/versions.txt",
    )
    # Candidate runtime deps, pinned to the scaffold uv.lock (Track A owns
    # uv.lock; re-verify these four at the contract freeze).
    .pip_install(
        "fastapi==0.141.1",
        "uvicorn[standard]==0.53.0",
        "pydantic==2.13.5",
        "httpx==0.28.1",
    )
    .add_local_file(
        _IMAGE_DIR / "start_desktop_world.sh", f"{_REMOTE_DIR}/start_desktop_world.sh", copy=True
    )
    .add_local_file(
        _IMAGE_DIR / "cua_capabilities.json", f"{_REMOTE_DIR}/cua_capabilities.json", copy=True
    )
    .run_commands("chmod 755 /opt/nightwatch/start_desktop_world.sh")
    .workdir("/opt/nightwatch")
)

# --- dev-only diagnostic app (never deployed; needs no secrets) --------------

app = modal.App("nightwatch-b-desktop-image")


def _run(*command: str) -> str:
    return subprocess.run(command, capture_output=True, text=True, check=False).stdout.strip()


@app.function(image=DESKTOP_IMAGE, timeout=600)
def desktop_image_report() -> dict[str, object]:
    """Prove the pinned image contents without starting a desktop."""
    return {
        "versions": _run("cat", "/opt/nightwatch/versions.txt"),
        "docker_image": DESKTOP_IMAGE.object_id or "unresolved",
        "app_uid": _run("id", "-u", APP_USER),
        "controller_uid": _run("id", "-u", CTL_USER),
        "app_home_mode": _run("stat", "-c", "%a", f"/home/{APP_USER}"),
        "controller_home_mode": _run("stat", "-c", "%a", f"/home/{CTL_USER}"),
        "start_script": _run("ls", "-l", "/opt/nightwatch/start_desktop_world.sh"),
        "manifest": json.loads(_run("cat", "/opt/nightwatch/cua_capabilities.json")),
    }


@app.local_entrypoint()
def main() -> None:
    print(json.dumps(desktop_image_report.remote(), indent=2, default=str))
