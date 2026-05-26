"""
ble_server.py — EVA BLE GATT Peripheral for Raspberry Pi Zero 2W.

Exposes three characteristics to the phone:
  MOOD_CHAR  (write)  — phone pushes mood + stats JSON
  PREFS_CHAR (r/w)    — phone writes onboarding prefs; also readable for restore
  CMD_CHAR   (write)  — phone sends activity/game/proximity commands

All incoming data is base64-encoded JSON.  On each write this server appends
a structured event line to /tmp/pal.events so main.py can react.

Run as root (required for bluezero GATT peripheral):
    sudo python3 ble_server.py

Requires:
    pip3 install bluezero
    sudo systemctl enable --now bluetooth
    sudo bluetoothctl power on
"""

from __future__ import annotations
import json
import base64
import logging
import threading
from pathlib import Path

from bluezero import peripheral, adapter

log = logging.getLogger("ble_server")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

# ── UUIDs (must match BLE constants in the mobile app) ───────────────────────
EVA_SERVICE_UUID = 'a1f7b540-0f8e-4a64-a027-f21f65ff8c1d'
MOOD_CHAR_UUID   = 'a1f7b541-0f8e-4a64-a027-f21f65ff8c1d'
PREFS_CHAR_UUID  = 'a1f7b542-0f8e-4a64-a027-f21f65ff8c1d'
CMD_CHAR_UUID    = 'a1f7b543-0f8e-4a64-a027-f21f65ff8c1d'

EVENT_FILE = Path('/run/pal.events')
PREFS_FILE = Path('/run/pal.prefs.json')

# ── Internal state ────────────────────────────────────────────────────────────
_prefs_bytes: list[int] = []
_lock = threading.Lock()


def _emit(line: str) -> None:
    """Append one event line to /tmp/pal.events (main.py drains this)."""
    try:
        # Ensure file exists so main.py can open it in r+ mode.
        if not EVENT_FILE.exists():
            EVENT_FILE.touch(mode=0o666)
        with open(EVENT_FILE, 'a') as f:
            f.write(line + '\n')
    except Exception as e:
        log.warning("emit error: %s", e)


def _decode(value: list[int]) -> dict | None:
    """Decode a list of bytes that is base64-encoded JSON."""
    try:
        raw = bytes(value)
        return json.loads(base64.b64decode(raw).decode())
    except Exception as e:
        log.warning("decode error: %s", e)
        return None


# ── Characteristic callbacks ─────────────────────────────────────────────────

def read_prefs() -> list[int]:
    with _lock:
        if _prefs_bytes:
            return _prefs_bytes
    # Load from persisted file if available.
    try:
        data = PREFS_FILE.read_bytes()
        return list(data)
    except Exception:
        return list(base64.b64encode(b'{}'))


def write_prefs(value: list[int], options: dict) -> None:
    data = _decode(value)
    if data is None:
        return
    log.info("prefs updated: %s", data)
    with _lock:
        _prefs_bytes[:] = value
    try:
        PREFS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2))
        log.info("prefs saved to %s", PREFS_FILE)
    except Exception as e:
        log.warning("prefs save error: %s", e)
    _emit(f'ble_prefs {json.dumps(data)}')


def write_mood(value: list[int], options: dict) -> None:
    data = _decode(value)
    if data is None:
        return
    mood  = data.get('mood', 'neutral')
    stats = data.get('stats', {})
    log.info("mood: %s  stats: %s", mood, stats)
    _emit(f'ble_mood {mood} {json.dumps(stats)}')


def write_cmd(value: list[int], options: dict) -> None:
    data = _decode(value)
    if data is None:
        return
    cmd = data.get('cmd', '')
    log.info("cmd: %s", data)

    if cmd == 'proximity':
        level = data.get('level', 'medium')
        _emit(f'ble_proximity {level}')

    elif cmd == 'activity':
        atype = data.get('type', '')
        _emit(f'ble_activity {atype} {json.dumps(data)}')

    elif cmd == 'game':
        gtype = data.get('type', '')
        _emit(f'ble_game {gtype} {json.dumps(data)}')

    else:
        _emit(f'ble_cmd {json.dumps(data)}')


# ── Connection callbacks ──────────────────────────────────────────────────────

def on_connect(device_path: str) -> None:
    log.info("phone connected: %s", device_path)
    _emit('ble_connect')


def on_disconnect(device_path: str) -> None:
    log.info("phone disconnected: %s", device_path)
    _emit('ble_disconnect')


# ── Build + publish the peripheral ───────────────────────────────────────────

def main() -> None:
    # Grab first available adapter address.
    try:
        addr = list(adapter.Adapter.available())[0].address
    except (IndexError, Exception) as e:
        log.error("No Bluetooth adapter found: %s", e)
        return

    log.info("Using adapter %s", addr)

    pal = peripheral.Peripheral(addr, local_name='EVA-001', appearance=0x0180)

    pal.add_service(srv_id=1, uuid=EVA_SERVICE_UUID, primary=True)

    # MOOD characteristic — write only from phone side
    pal.add_characteristic(
        srv_id=1, chr_id=1,
        uuid=MOOD_CHAR_UUID,
        value=[],
        notifying=False,
        flags=['write', 'write-without-response'],
        read_callback=None,
        write_callback=write_mood,
        notify_callback=None,
    )

    # PREFS characteristic — read/write (phone writes on onboarding, reads on restore)
    pal.add_characteristic(
        srv_id=1, chr_id=2,
        uuid=PREFS_CHAR_UUID,
        value=list(base64.b64encode(b'{}')),
        notifying=False,
        flags=['read', 'write', 'write-without-response'],
        read_callback=read_prefs,
        write_callback=write_prefs,
        notify_callback=None,
    )

    # CMD characteristic — write only
    pal.add_characteristic(
        srv_id=1, chr_id=3,
        uuid=CMD_CHAR_UUID,
        value=[],
        notifying=False,
        flags=['write', 'write-without-response'],
        read_callback=None,
        write_callback=write_cmd,
        notify_callback=None,
    )

    pal.on_connect    = on_connect
    pal.on_disconnect = on_disconnect

    # Ensure event file exists so main.py can open it.
    if not EVENT_FILE.exists():
        EVENT_FILE.touch(mode=0o666)

    log.info("EVA-001 BLE peripheral publishing…  (Ctrl-C to stop)")
    pal.publish()


if __name__ == '__main__':
    main()
