#!/usr/bin/env bash
# NightWatch Track B — boot one isolated desktop world inside a Modal Sandbox.
#
# Plan references: §11.6 (CUA inside every candidate Sandbox), §11.8 (gate),
# §12.2 (world lifecycle). Runs as root, because Modal's Sandbox.exec has no
# per-user parameter; every process is started through an explicit setpriv
# privilege drop and the effective UIDs are recorded in the evidence file.
#
# Layout it enforces:
#   nightwatch_controller  owns X11 cookie, D-Bus session, Openbox, the CUA
#                          Driver daemon and (later) Chromium; home 0700.
#   nightwatch_app         owns only the candidate bundle and app process;
#                          receives only NW_PROVIDER_TOKEN when supplied.
#   /run/nightwatch        0770 root:nightwatch_controller — the app user
#                          cannot traverse it, so it can reach neither the
#                          controller socket nor the controller env file.
#   X11                     Xvfb with a controller-owned auth cookie; the app
#                          user has no XAUTHORITY, so it cannot use the display.
#
# Parameters (environment):
#   NW_APP_PORT         candidate app port (default 8080; manifest origin must match)
#   NW_APP_DIR          candidate bundle directory (default /opt/nightwatch/app)
#   NW_APP_CMD          app start command (default a loopback static server)
#   NW_APP_READY_PATH   readiness path curl'd before success (default /)
#   NW_PROVIDER_TOKEN   optional short-lived provider token, app user only
#
# Outputs:
#   /run/nightwatch/world-evidence.json   uids, pids, modes, versions, probe
#   /run/nightwatch/as_controller.sh      runs argv as the controller identity
#
# Teardown is the trusted runner's job: end the CUA session, then terminate the
# Sandbox (which kills every process in it).

set -euo pipefail

APP_PORT="${NW_APP_PORT:-8080}"
APP_DIR="${NW_APP_DIR:-/opt/nightwatch/app}"
APP_CMD="${NW_APP_CMD:-python3 -m http.server ${APP_PORT} --bind 127.0.0.1}"
APP_READY_PATH="${NW_APP_READY_PATH:-/}"

APP_USER="nightwatch_app"
CTL_USER="nightwatch_controller"
RUN_DIR="/run/nightwatch"
DISPLAY_NUM=":99"
CUA_SOCK="${RUN_DIR}/cua.sock"
MANIFEST="${RUN_DIR}/cua-capabilities.json"
MANIFEST_SRC="/opt/nightwatch/cua_capabilities.json"
XAUTH="${RUN_DIR}/xauthority"
CTL_ENV="${RUN_DIR}/controller.env"
EVIDENCE="${RUN_DIR}/world-evidence.json"

die() { echo "nightwatch: $*" >&2; exit 1; }

[ "$(id -u)" = "0" ] || die "must run as root inside the sandbox"
id "$APP_USER" >/dev/null 2>&1 || die "missing user $APP_USER (wrong image?)"
id "$CTL_USER" >/dev/null 2>&1 || die "missing user $CTL_USER (wrong image?)"
[ -f "$MANIFEST_SRC" ] || die "missing $MANIFEST_SRC (wrong image?)"

APP_UID="$(id -u "$APP_USER")"
APP_GID="$(id -g "$APP_USER")"
CTL_UID="$(id -u "$CTL_USER")"
CTL_GID="$(id -g "$CTL_USER")"

install -d -o root -g "$CTL_USER" -m 0770 "$RUN_DIR"
install -d -o "$CTL_USER" -g "$CTL_USER" -m 0700 "/run/user/$CTL_UID"

# Run argv as the controller identity with a minimal environment.
# Extra environment is passed by prefixing: as_ctl env KEY=value cmd ...
as_ctl() {
  setpriv --reuid="$CTL_UID" --regid="$CTL_GID" --init-groups \
    env -i PATH=/usr/local/bin:/usr/bin:/bin \
    HOME="/home/$CTL_USER" USER="$CTL_USER" LOGNAME="$CTL_USER" \
    XDG_RUNTIME_DIR="/run/user/$CTL_UID" "$@"
}

# ---------------------------------------------------------------- X11 display
COOKIE="$(mcookie)"
as_ctl install -m 0600 /dev/null "$XAUTH"
as_ctl xauth -f "$XAUTH" add "$DISPLAY_NUM" . "$COOKIE"

as_ctl env DISPLAY="$DISPLAY_NUM" XAUTHORITY="$XAUTH" \
  Xvfb "$DISPLAY_NUM" -screen 0 1280x800x24 -nolisten tcp -auth "$XAUTH" \
  >"$RUN_DIR/xvfb.log" 2>&1 &

for _ in $(seq 1 50); do
  if as_ctl env DISPLAY="$DISPLAY_NUM" XAUTHORITY="$XAUTH" xdpyinfo >/dev/null 2>&1; then
    break
  fi
  sleep 0.2
done
if ! as_ctl env DISPLAY="$DISPLAY_NUM" XAUTHORITY="$XAUTH" xdpyinfo >/dev/null 2>&1; then
  tail -n 40 "$RUN_DIR/xvfb.log" >&2 || true
  die "Xvfb did not become ready"
fi

# ------------------------------------------------------------- D-Bus / AT-SPI
BUS_INFO="$(as_ctl dbus-daemon --session --fork --print-address=1 --print-pid=1)"
DBUS_ADDR="$(printf '%s\n' "$BUS_INFO" | sed -n '1p')"
[ -n "$DBUS_ADDR" ] || die "dbus-daemon did not report an address"

ATSPI_BIN=""
for candidate in /usr/libexec/at-spi-bus-launcher /usr/lib/at-spi2-core/at-spi-bus-launcher; do
  if [ -x "$candidate" ]; then
    ATSPI_BIN="$candidate"
    break
  fi
done

CTL_DBUS_ENV=(env DISPLAY="$DISPLAY_NUM" XAUTHORITY="$XAUTH"
  DBUS_SESSION_BUS_ADDRESS="$DBUS_ADDR"
  XDG_RUNTIME_DIR="/run/user/$CTL_UID"
  GTK_MODULES=gail:atk-bridge NO_AT_BRIDGE=0)

if [ -n "$ATSPI_BIN" ]; then
  as_ctl "${CTL_DBUS_ENV[@]}" "$ATSPI_BIN" --launch-immediately \
    >"$RUN_DIR/at-spi.log" 2>&1 &
fi

# Controller env file, private to the controller identity.
umask 077
{
  printf 'DISPLAY=%s\n' "$DISPLAY_NUM"
  printf 'XAUTHORITY=%s\n' "$XAUTH"
  printf 'DBUS_SESSION_BUS_ADDRESS=%s\n' "$DBUS_ADDR"
  printf 'XDG_RUNTIME_DIR=%s\n' "/run/user/$CTL_UID"
} >"$CTL_ENV"
chown "$CTL_USER:$CTL_USER" "$CTL_ENV"
chmod 0600 "$CTL_ENV"
umask 022

# ------------------------------------------------------------------- Openbox
as_ctl "${CTL_DBUS_ENV[@]}" openbox --sm-disable >"$RUN_DIR/openbox.log" 2>&1 &
for _ in $(seq 1 25); do
  pgrep -u "$CTL_UID" -x openbox >/dev/null 2>&1 && break
  sleep 0.2
done

# ------------------------------------------------- capability manifest (exact origin)
python3 - "$MANIFEST_SRC" "$MANIFEST" "$APP_PORT" <<'PY'
import json
import sys

source, destination, port = sys.argv[1], sys.argv[2], int(sys.argv[3])
with open(source, encoding="utf-8") as handle:
    manifest = json.load(handle)
manifest["resources"]["browser"]["origins"] = [f"http://127.0.0.1:{port}"]
with open(destination, "w", encoding="utf-8") as handle:
    json.dump(manifest, handle, indent=2, sort_keys=True)
PY
chown "$CTL_USER:$CTL_USER" "$MANIFEST"
chmod 0600 "$MANIFEST"
MANIFEST_SHA="$(sha256sum "$MANIFEST" | awk '{print $1}')"

# --------------------------------------------------------------- CUA Driver
# Bounded mode with a reviewed manifest; telemetry and update checks off.
as_ctl env HOME="/home/$CTL_USER" cua-driver telemetry disable >/dev/null 2>&1 || true
as_ctl "${CTL_DBUS_ENV[@]}" \
  CUA_DRIVER_RS_TELEMETRY_ENABLED=false CUA_DRIVER_RS_UPDATE_CHECK=false \
  nohup cua-driver serve --socket "$CUA_SOCK" \
    --permission-mode bounded \
    --capability-manifest "$MANIFEST" \
    --approve-capability-manifest \
  >"$RUN_DIR/cua-driver.log" 2>&1 &

for _ in $(seq 1 100); do
  [ -S "$CUA_SOCK" ] && break
  sleep 0.2
done
if [ ! -S "$CUA_SOCK" ]; then
  tail -n 60 "$RUN_DIR/cua-driver.log" >&2 || true
  die "CUA driver socket did not appear"
fi
chmod 0600 "$CUA_SOCK"

# Best-effort probe: a start/end session pair proves the daemon answers over
# its socket with manifest-allowed calls. Desktop-wide enumeration
# (list_windows with no pid) is correctly outside this browser-only manifest.
CUA_PROBE="$(as_ctl timeout 15 cua-driver call start_session '{"session":"bootstrap-probe"}' --socket "$CUA_SOCK" 2>&1 || true)"
as_ctl timeout 15 cua-driver call end_session '{"session":"bootstrap-probe"}' --socket "$CUA_SOCK" >/dev/null 2>&1 || true
CUA_PROBE_STATUS="ok"
case "$CUA_PROBE" in
  *refus*|*denied*|*'not running'*|*Error*) CUA_PROBE_STATUS="error" ;;
esac

# -------------------------------------------------------------- candidate app
mkdir -p "$APP_DIR"
chown -R "$APP_USER:$APP_GID" "$APP_DIR"

APP_ENV=(env -i PATH=/usr/local/bin:/usr/bin:/bin TZ=UTC
  HOME="/home/$APP_USER" USER="$APP_USER" LOGNAME="$APP_USER")
if [ -n "${NW_PROVIDER_TOKEN:-}" ]; then
  APP_ENV+=(NW_PROVIDER_TOKEN="$NW_PROVIDER_TOKEN")
fi

setpriv --reuid="$APP_UID" --regid="$APP_GID" --init-groups \
  "${APP_ENV[@]}" bash -c "cd '$APP_DIR' && exec $APP_CMD" \
  >"/home/$APP_USER/app.log" 2>&1 &

APP_READY=0
for _ in $(seq 1 100); do
  if curl -fsS -o /dev/null "http://127.0.0.1:${APP_PORT}${APP_READY_PATH}"; then
    APP_READY=1
    break
  fi
  sleep 0.2
done
if [ "$APP_READY" != "1" ]; then
  tail -n 60 "/home/$APP_USER/app.log" >&2 || true
  die "candidate app did not answer on 127.0.0.1:${APP_PORT}${APP_READY_PATH}"
fi

# ------------------------------------------------- controller-owned browser
# The world's Chromium is launched by a generated helper, owned by the
# controller identity, with a world-local mode-0700 profile and forced
# accessibility. The helper is the single source of truth for the launch
# because Chrome must be restarted once after CUA enables the profile's
# remote-debugging setting (browser_requires_setup -> restart -> attach):
# launch-time debugging flags are deliberately ignored by the driver, so the
# endpoint appears only after the product's own auto-connect setting is on.
#
# Probe evidence, driver 0.28.2: (1) with an origin-scoped bounded manifest the
# typed surface refuses the first browser_navigate from a fresh about:blank
# tab for every manifest origin spelling -> the browser must start at an
# allowed origin; (2) launching through the /usr/bin wrapper makes the app
# identity miss the manifest entry -> launch the binary directly; (3) the
# remote-debugging setting is toggled once by CUA's bounded setup route and
# survives a restart in this world-local profile.
cat >"$RUN_DIR/launch_browser.sh" <<'WRAPPER'
#!/usr/bin/env bash
set -euo pipefail
RUN_DIR=/run/nightwatch
CTL_USER=nightwatch_controller
CTL_UID="$(id -u "$CTL_USER")"
CTL_GID="$(id -g "$CTL_USER")"
PROFILE="${RUN_DIR}/chrome-profile"
BROWSER_START_URL="${NW_BROWSER_START_URL:-http://127.0.0.1:8080/}"
ENV_FILE="${RUN_DIR}/controller.env"

DISPLAY=""; XAUTHORITY=""; DBUS_SESSION_BUS_ADDRESS=""; XDG_RUNTIME_DIR=""
while IFS='=' read -r key value; do
  case "$key" in
    DISPLAY) DISPLAY="$value" ;;
    XAUTHORITY) XAUTHORITY="$value" ;;
    DBUS_SESSION_BUS_ADDRESS) DBUS_SESSION_BUS_ADDRESS="$value" ;;
    XDG_RUNTIME_DIR) XDG_RUNTIME_DIR="$value" ;;
  esac
done <"$ENV_FILE"

as_ctl() {
  setpriv --reuid="$CTL_UID" --regid="$CTL_GID" --init-groups \
    env -i PATH=/usr/local/bin:/usr/bin:/bin HOME="/home/$CTL_USER" USER="$CTL_USER" \
    LOGNAME="$CTL_USER" DISPLAY="$DISPLAY" XAUTHORITY="$XAUTHORITY" \
    DBUS_SESSION_BUS_ADDRESS="$DBUS_SESSION_BUS_ADDRESS" \
    XDG_RUNTIME_DIR="$XDG_RUNTIME_DIR" "$@"
}

for wid in $(as_ctl xprop -root _NET_CLIENT_LIST 2>/dev/null | sed -n 's/.*window id #//p' | tr ',' ' '); do
  owner="$(as_ctl xprop -id "$wid" _NET_WM_PID 2>/dev/null | sed -n 's/.*= //p' | tr -d ' ')"
  if [ -n "$owner" ] && [ -e "/proc/$owner/exe" ] && \
     [ "$(readlink -f "/proc/$owner/exe")" = "/opt/google/chrome/chrome" ]; then
    kill -TERM "$owner" 2>/dev/null || true
  fi
done
sleep 0.5
pkill -u "$CTL_UID" -f '/opt/google/chrome/chrome' 2>/dev/null || true
sleep 0.5

install -d -o "$CTL_USER" -g "$CTL_USER" -m 0700 "$PROFILE"
as_ctl nohup /opt/google/chrome/chrome \
  --user-data-dir="$PROFILE" \
  --force-renderer-accessibility \
  --no-first-run --no-default-browser-check \
  --no-sandbox --disable-dev-shm-usage \
  --window-size=1050,780 --window-position=10,10 \
  "$BROWSER_START_URL" \
  >"$RUN_DIR/chrome.log" 2>&1 &

PID=""
WINDOW_ID=""
for _ in $(seq 1 150); do
  for wid in $(as_ctl xprop -root _NET_CLIENT_LIST 2>/dev/null | sed -n 's/.*window id #//p' | tr ',' ' '); do
    owner="$(as_ctl xprop -id "$wid" _NET_WM_PID 2>/dev/null | sed -n 's/.*= //p' | tr -d ' ')"
    if [ -n "$owner" ] && [ -e "/proc/$owner/exe" ] && \
       [ "$(readlink -f "/proc/$owner/exe")" = "/opt/google/chrome/chrome" ]; then
      PID="$owner"
      WINDOW_ID="$wid"
      break
    fi
  done
  [ -n "$PID" ] && break
  sleep 0.2
done
if [ -z "$PID" ]; then
  tail -n 60 "$RUN_DIR/chrome.log" >&2 || true
  exit 1
fi

python3 - "$RUN_DIR/browser.json" "$PID" "$WINDOW_ID" "$BROWSER_START_URL" <<'PY'
import json
import sys
import time

path, pid, window_id, start_url = sys.argv[1:5]
window_value = int(window_id, 16) if window_id.lower().startswith("0x") else int(window_id)
with open(path, "w", encoding="utf-8") as handle:
    json.dump(
        {
            "pid": int(pid),
            "window_id": window_value,
            "start_url": start_url,
            "started_monotonic_ns": time.monotonic_ns(),
        },
        handle,
        indent=2,
        sort_keys=True,
    )
print("browser ready")
PY
WRAPPER
chmod 0755 "$RUN_DIR/launch_browser.sh"
"$RUN_DIR/launch_browser.sh"
CHROME_PID="$(python3 -c "import json;print(json.load(open('/run/nightwatch/browser.json'))['pid'])")"

# ------------------------------------------------------- runner helper wrapper
cat >"$RUN_DIR/as_controller.sh" <<'WRAPPER'
#!/usr/bin/env bash
# Run argv as nightwatch_controller with the world's display/D-Bus environment.
set -euo pipefail
CTL_USER=nightwatch_controller
CTL_UID="$(id -u "$CTL_USER")"
CTL_GID="$(id -g "$CTL_USER")"
ENV_FILE=/run/nightwatch/controller.env
[ -r "$ENV_FILE" ] || { echo "as_controller: missing $ENV_FILE" >&2; exit 1; }
DISPLAY=""; XAUTHORITY=""; DBUS_SESSION_BUS_ADDRESS=""; XDG_RUNTIME_DIR=""
while IFS='=' read -r key value; do
  case "$key" in
    DISPLAY) DISPLAY="$value" ;;
    XAUTHORITY) XAUTHORITY="$value" ;;
    DBUS_SESSION_BUS_ADDRESS) DBUS_SESSION_BUS_ADDRESS="$value" ;;
    XDG_RUNTIME_DIR) XDG_RUNTIME_DIR="$value" ;;
  esac
done <"$ENV_FILE"
exec setpriv --reuid="$CTL_UID" --regid="$CTL_GID" --init-groups \
  env -i PATH=/usr/local/bin:/usr/bin:/bin \
  HOME="/home/$CTL_USER" USER="$CTL_USER" LOGNAME="$CTL_USER" \
  DISPLAY="$DISPLAY" XAUTHORITY="$XAUTHORITY" \
  DBUS_SESSION_BUS_ADDRESS="$DBUS_SESSION_BUS_ADDRESS" \
  XDG_RUNTIME_DIR="$XDG_RUNTIME_DIR" \
  GTK_MODULES=gail:atk-bridge NO_AT_BRIDGE=0 \
  "$@"
WRAPPER
chmod 0755 "$RUN_DIR/as_controller.sh"

# -------------------------------------------------------------------- evidence
XVFB_PID="$(pgrep -u "$CTL_UID" -x Xvfb | head -n1 || true)"
OPENBOX_PID="$(pgrep -u "$CTL_UID" -x openbox | head -n1 || true)"
DBUS_PID="$(pgrep -u "$CTL_UID" -x dbus-daemon | head -n1 || true)"
CUA_PID="$(pgrep -u "$CTL_UID" -f 'cua-driver serve' | head -n1 || true)"
APP_PID="$(pgrep -u "$APP_UID" -n . | head -n1 || true)"

NW_EV_APP_USER="$APP_USER" NW_EV_APP_UID="$APP_UID" \
NW_EV_CTL_USER="$CTL_USER" NW_EV_CTL_UID="$CTL_UID" \
NW_EV_APP_PORT="$APP_PORT" NW_EV_APP_DIR="$APP_DIR" \
NW_EV_DISPLAY="$DISPLAY_NUM" NW_EV_CUA_SOCK="$CUA_SOCK" \
NW_EV_MANIFEST_SHA="$MANIFEST_SHA" NW_EV_CUA_PROBE_STATUS="$CUA_PROBE_STATUS" \
NW_EV_CUA_PROBE="$(printf '%s' "$CUA_PROBE" | head -c 800)" \
NW_EV_XVFB_PID="$XVFB_PID" NW_EV_OPENBOX_PID="$OPENBOX_PID" \
NW_EV_DBUS_PID="$DBUS_PID" NW_EV_CUA_PID="$CUA_PID" NW_EV_APP_PID="$APP_PID" \
NW_EV_ATSPI_BIN="$ATSPI_BIN" \
NW_EV_CHROME_PID="$CHROME_PID" \
NW_EV_CHROME_PROFILE="${RUN_DIR}/chrome-profile" \
NW_EV_BROWSER_START_URL="http://127.0.0.1:${APP_PORT}/" \
NW_EV_BROWSER_JSON="${RUN_DIR}/browser.json" \
python3 - "$EVIDENCE" <<'PY'
import json
import os
import subprocess
import sys
import time


def run(*command: str) -> str:
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    return (result.stdout or result.stderr).strip()


def ok(*command: str) -> bool:
    return subprocess.run(command, capture_output=True, check=False).returncode == 0


chrome_profile = os.environ["NW_EV_CHROME_PROFILE"]
browser_json: dict[str, object] = {}
browser_json_path = os.environ["NW_EV_BROWSER_JSON"]
if ok("test", "-f", browser_json_path):
    with open(browser_json_path, encoding="utf-8") as handle:
        browser_json = json.load(handle)
evidence = {
    "started_monotonic_ns": time.monotonic_ns(),
    "app_user": os.environ["NW_EV_APP_USER"],
    "app_uid": int(os.environ["NW_EV_APP_UID"]),
    "controller_user": os.environ["NW_EV_CTL_USER"],
    "controller_uid": int(os.environ["NW_EV_CTL_UID"]),
    "app_port": int(os.environ["NW_EV_APP_PORT"]),
    "app_dir": os.environ["NW_EV_APP_DIR"],
    "display": os.environ["NW_EV_DISPLAY"],
    "cua_socket": os.environ["NW_EV_CUA_SOCK"],
    "cua_socket_mode": run("stat", "-c", "%a %U:%G", os.environ["NW_EV_CUA_SOCK"]),
    "cua_manifest_sha256": os.environ["NW_EV_MANIFEST_SHA"],
    "cua_probe_status": os.environ["NW_EV_CUA_PROBE_STATUS"],
    "cua_probe_output": os.environ["NW_EV_CUA_PROBE"],
    "xvfb_pid": os.environ["NW_EV_XVFB_PID"] or None,
    "openbox_pid": os.environ["NW_EV_OPENBOX_PID"] or None,
    "dbus_pid": os.environ["NW_EV_DBUS_PID"] or None,
    "cua_driver_pid": os.environ["NW_EV_CUA_PID"] or None,
    "app_pid": os.environ["NW_EV_APP_PID"] or None,
    "at_spi_launcher": os.environ["NW_EV_ATSPI_BIN"] or None,
    "chrome_pid": os.environ["NW_EV_CHROME_PID"] or None,
    "chrome_profile": chrome_profile,
    "chrome_profile_mode": run("stat", "-c", "%a %U:%G", chrome_profile),
    "browser_start_url": os.environ["NW_EV_BROWSER_START_URL"],
    "browser_window_id": browser_json.get("window_id"),
    "browser_started_monotonic_ns": browser_json.get("started_monotonic_ns"),
    "cua_driver_version": run("cua-driver", "--version"),
    "browser_version": run("google-chrome", "--version") or run("chromium", "--version"),
    "run_dir_mode": run("stat", "-c", "%a %U:%G", "/run/nightwatch"),
    "controller_home_mode": run("stat", "-c", "%a %U:%G", "/home/nightwatch_controller"),
    "app_home_mode": run("stat", "-c", "%a %U:%G", "/home/nightwatch_app"),
}
with open(sys.argv[1], "w", encoding="utf-8") as handle:
    json.dump(evidence, handle, indent=2, sort_keys=True)
PY
chmod 0644 "$EVIDENCE"

cat "$EVIDENCE"
echo "WORLD_READY=$EVIDENCE"
