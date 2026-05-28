"""
ble_server.py — EVA BLE GATT Peripheral for Raspberry Pi Zero 2W.

Characteristics:
  MOOD_CHAR  (write)         — phone pushes mood indicator for OLED sync
  PREFS_CHAR (r/w)           — onboarding prefs; includes _pin_ok flag
  CMD_CHAR   (write)         — activity/game/proximity/media commands
  STATE_CHAR (read + notify) — Pi pushes stat/meta snapshot to phone every 500 ms

All incoming data is base64-encoded JSON.  Writes append structured event lines
to /run/pal.events; main.py reads and processes them.

Run as root (required for bluezero GATT peripheral):
    sudo python3 ble_server.py
"""

from __future__ import annotations
import json
import base64
import logging
import random
import subprocess
import threading
import time
from pathlib import Path

from bluezero import peripheral, adapter
from gi.repository import GLib

log = logging.getLogger("ble_server")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

# ── UUIDs (must match BLE constants in the mobile app) ───────────────────────
EVA_SERVICE_UUID  = 'a1f7b540-0f8e-4a64-a027-f21f65ff8c1d'
MOOD_CHAR_UUID    = 'a1f7b541-0f8e-4a64-a027-f21f65ff8c1d'
PREFS_CHAR_UUID   = 'a1f7b542-0f8e-4a64-a027-f21f65ff8c1d'
CMD_CHAR_UUID     = 'a1f7b543-0f8e-4a64-a027-f21f65ff8c1d'
STATE_CHAR_UUID   = 'a1f7b544-0f8e-4a64-a027-f21f65ff8c1d'

EVENT_FILE  = Path('/run/pal.events')
PREFS_FILE  = Path('/run/pal.prefs.json')
PHONE_FILE  = Path('/run/pal.phone.json')   # compact state written by main.py

# ── Internal state ────────────────────────────────────────────────────────────
_prefs_bytes: list[int] = []
_lock        = threading.Lock()
_pending_pin: str   = ''     # 6-digit PIN shown on OLED for current connection
_pin_verified: bool = False  # set True after correct verify_pin command
_pin_generated_at: float = 0.0

# Keep the same PIN for this many seconds across rapid reconnects.
# Prevents a new PIN being generated mid-entry when Android briefly drops the link.
_PIN_TTL: float = 120.0


def _clear_bonds() -> None:
    """Remove any bonded/paired phone devices on startup.

    Prevents Android OS-level auto-reconnect loops that fight with our
    app-level GATT connection.  We want GATT-only, no bonding.
    """
    try:
        out = subprocess.run(
            ['bluetoothctl', 'devices', 'Paired'],
            capture_output=True, text=True, timeout=5,
        ).stdout
        for line in out.splitlines():
            parts = line.strip().split()
            if len(parts) >= 2 and parts[0] == 'Device':
                mac = parts[1]
                subprocess.run(['bluetoothctl', 'remove', mac],
                               capture_output=True, timeout=5)
                log.info("Removed stale bond: %s", mac)
    except Exception as e:
        log.warning("Bond cleanup error: %s", e)


def _emit(line: str) -> None:
    """Append one event line to /run/pal.events (main.py drains this)."""
    try:
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
            # Include PIN status so phone can check verification result
            try:
                data = json.loads(bytes(_prefs_bytes).decode())
            except Exception:
                data = {}
            data['_pin_ok'] = _pin_verified
            return list(base64.b64encode(json.dumps(data).encode()))
    try:
        raw  = json.loads(PREFS_FILE.read_text())
        raw['_pin_ok'] = _pin_verified
        return list(base64.b64encode(json.dumps(raw).encode()))
    except Exception:
        payload = json.dumps({'_pin_ok': _pin_verified}).encode()
        return list(base64.b64encode(payload))


def write_prefs(value: list[int], options: dict) -> None:
    data = _decode(value)
    if data is None:
        return
    log.info("prefs updated: %s", data)
    with _lock:
        _prefs_bytes[:] = value
    try:
        PREFS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2))
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
    global _pin_verified
    try:
        Path('/tmp/ble_cmd_called').write_text(f"len={len(value)} val={value[:8]}")
    except Exception:
        pass
    log.info("write_cmd RAW len=%d", len(value))
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
    elif cmd == 'verify_pin':
        entered = str(data.get('pin', ''))
        if entered == _pending_pin:
            _pin_verified = True
            log.info("PIN verified OK")
            _emit('ble_pin_ok')
        else:
            log.info("PIN mismatch: got %s expected %s", entered, _pending_pin)
            _emit('ble_pin_fail')
    elif cmd == 'skip_pin':
        _pin_verified = True
        log.info("PIN skipped (returning device)")
        _emit('ble_pin_skip')
    else:
        _emit(f'ble_cmd {json.dumps(data)}')


# ── STATE_CHAR callbacks + GLib push timer ────────────────────────────────────

_state_char_ref  = None   # localGATT.Characteristic for STATE_CHAR, set in main()
_last_phone_hash = 0


def read_state() -> list[int]:
    # Merge pending_pin + _pin_ok so a DIRECT read carries them too — not only the
    # notify path. The phone relies on this to verify the PIN even when notifications
    # or the verify_pin write are dropped on a flaky link.
    try:
        data = json.loads(PHONE_FILE.read_bytes())
    except Exception:
        data = {}
    data['pending_pin'] = _pending_pin
    data['_pin_ok'] = _pin_verified
    try:
        merged = json.dumps(data, separators=(',', ':')).encode()
        return list(base64.b64encode(merged))
    except Exception:
        return list(base64.b64encode(b'{}'))


def on_state_notify(notifying: bool, characteristic=None) -> None:
    log.info("state notify subscription: %s", notifying)


def _notify_state_tick() -> bool:
    """GLib timer — polls /run/pal.phone.json every 500 ms and notifies if changed."""
    global _last_phone_hash
    if _state_char_ref is None or not PHONE_FILE.exists():
        return True
    try:
        content = PHONE_FILE.read_bytes()
        # Merge pending_pin + _pin_ok so phone can verify locally (writes may be unreliable)
        data = json.loads(content)
        data['pending_pin'] = _pending_pin
        data['_pin_ok'] = _pin_verified
        merged = json.dumps(data, separators=(',', ':')).encode()
        h = hash(merged)
        if h != _last_phone_hash:
            _last_phone_hash = h
            _state_char_ref.set_value(list(base64.b64encode(merged)))
    except Exception as e:
        log.warning("state notify error: %s", e)
    return True  # keep timer running


# ── Connection callbacks ──────────────────────────────────────────────────────

def on_connect(device_path: str) -> None:
    global _pending_pin, _pin_verified, _pin_generated_at
    now = time.monotonic()
    within_ttl = bool(_pending_pin) and (now - _pin_generated_at) <= _PIN_TTL
    if not within_ttl:
        # Fresh session: generate new PIN and reset verification state.
        # TTL window: keep the existing PIN (and _pin_verified flag) intact so that
        # a rapid reconnect during PIN entry or right after verify_pin doesn't break the flow.
        _pending_pin = f"{random.randint(0, 999999):06d}"
        _pin_generated_at = now
        _pin_verified = False
    log.info("phone connected: %s  PIN=%s  verified=%s  age=%.0fs",
             device_path, _pending_pin, _pin_verified, now - _pin_generated_at)
    _emit('ble_connect')
    _emit(f'ble_pin_show {_pending_pin}')


def on_disconnect(device_path: str) -> None:
    log.info("phone disconnected: %s", device_path)
    _emit('ble_disconnect')


# ── Build + publish the peripheral ───────────────────────────────────────────

def main() -> None:
    # Remove any existing bonds — GATT-only, no pairing/bonding needed.
    _clear_bonds()

    try:
        addr = list(adapter.Adapter.available())[0].address
    except (IndexError, Exception) as e:
        log.error("No Bluetooth adapter found: %s", e)
        return

    log.info("Using adapter %s", addr)

    pal = peripheral.Peripheral(addr, local_name='EVA-001', appearance=0x0180)

    pal.add_service(srv_id=1, uuid=EVA_SERVICE_UUID, primary=True)

    pal.add_characteristic(
        srv_id=1, chr_id=1,
        uuid=MOOD_CHAR_UUID,
        value=[],
        notifying=False,
        flags=['write'],
        read_callback=None,
        write_callback=write_mood,
        notify_callback=None,
    )

    pal.add_characteristic(
        srv_id=1, chr_id=2,
        uuid=PREFS_CHAR_UUID,
        value=list(base64.b64encode(b'{}')),
        notifying=False,
        flags=['read', 'write'],
        read_callback=read_prefs,
        write_callback=write_prefs,
        notify_callback=None,
    )

    pal.add_characteristic(
        srv_id=1, chr_id=3,
        uuid=CMD_CHAR_UUID,
        value=[],
        notifying=False,
        flags=['write'],
        read_callback=None,
        write_callback=write_cmd,
        notify_callback=None,
    )

    pal.add_characteristic(
        srv_id=1, chr_id=4,
        uuid=STATE_CHAR_UUID,
        value=list(base64.b64encode(b'{}')),
        notifying=False,
        flags=['read', 'notify'],
        read_callback=read_state,
        write_callback=None,
        notify_callback=on_state_notify,
    )

    pal.on_connect    = on_connect
    pal.on_disconnect = on_disconnect

    if not EVENT_FILE.exists():
        EVENT_FILE.touch(mode=0o666)

    # Store reference to STATE_CHAR (last characteristic added) for GLib timer.
    global _state_char_ref
    _state_char_ref = pal.characteristics[-1]
    GLib.timeout_add(500, _notify_state_tick)

    log.info("EVA-001 BLE peripheral publishing…  (Ctrl-C to stop)")
    pal.publish()


if __name__ == '__main__':
    main()
