"""
main.py — EVA Pixel Pal main loop (Raspberry Pi, engine edition).

Pi is the single source of truth for all game state.  The mobile app is
a display-only client; it sends activity commands and receives stat updates.

BLE events arrive via /run/pal.events (written by ble_server.py):

  ble_connect                  — phone connected
  ble_disconnect               — phone disconnected
  ble_pin_show <pin>           — show pairing PIN on OLED
  ble_pin_ok                   — PIN verified → exit PIN display
  ble_pin_skip                 — saved device → skip PIN display
  ble_pin_fail                 — wrong PIN → brief angry face
  ble_proximity <level>        — close|medium|far
  ble_mood <mood>              — phone UI context (for OLED sync only)
  ble_activity <type> <json>   — user did an activity; json may include score
  ble_game <type> <json>       — game outcome; json may include score
  ble_prefs <json>             — onboarding prefs saved
  ble_cmd <json>               — generic: {cmd:"media",state:"music"|"video"|"none"}
                                          {cmd:"revive"}

Legacy direct events (kept for backward compat):
  feed / pet / play / sleep / speak / poke

Usage:
    sudo python3 main.py --driver luma          # real hardware
    python3 main.py --driver preview --once happy
"""

from __future__ import annotations
import argparse
import json
import random
import signal
import sys
import time
from pathlib import Path

from pixel_pal import (
    blank_canvas, draw_face, draw_wave_frame,
    draw_music_frame, draw_video_frame, draw_pin_frame,
    EXPRESSIONS, W, H,
)
from engine import EvaState, apply_activity, apply_decay, get_activity_expr, ambient_mood
from engine.expressions import MOOD_EXPR_MAP


# ============================================================
# Driver abstraction
# ============================================================

class PreviewDriver:
    def __init__(self, path: str = "/tmp/pal.png"):
        self.path = path
    def show(self, image):
        from PIL import Image as _I
        image.resize((W * 8, H * 8), _I.NEAREST).save(self.path)
    def close(self): pass


class LumaDriver:
    def __init__(self):
        from luma.core.interface.serial import spi
        from luma.oled.device import ssd1305
        serial = spi(port=0, device=0, gpio_DC=24, gpio_RST=25)
        self.device = ssd1305(serial, width=128, height=32)
    def show(self, image):
        self.device.display(image.convert("1"))
    def close(self):
        try: self.device.cleanup()
        except Exception: pass


class WaveshareDriver:
    def __init__(self):
        import SSD1305  # type: ignore
        self.disp = SSD1305.SSD1305()
        self.disp.Init()
        self.disp.clear()
    def show(self, image):
        self.disp.getbuffer(image)
        self.disp.ShowImage(self.disp.getbuffer(image))
    def close(self):
        try: self.disp.clear()
        except Exception: pass


def make_driver(name: str):
    if name == "luma":      return LumaDriver()
    if name == "waveshare": return WaveshareDriver()
    if name == "preview":   return PreviewDriver()
    raise ValueError(f"unknown driver: {name}")


# ============================================================
# Event file drain
# ============================================================

EVENT_FILE = Path("/run/pal.events")


def drain_events():
    if not EVENT_FILE.exists():
        return []
    try:
        with open(EVENT_FILE, "r+") as f:
            content = f.read()
            f.seek(0)
            f.truncate(0)
    except Exception:
        return []
    return [ln.strip() for ln in content.splitlines() if ln.strip()]


# ============================================================
# Wave animation (blocking, ~4 s)
# ============================================================

WAVE_CYCLES   = 3
WAVE_FPS      = 12
SLEEP_DELAY_S = 3.0


def play_wave_goodbye(driver, sleep_fn=None):
    frame_dur   = 1.0 / WAVE_FPS
    total_frames = WAVE_CYCLES * 12
    for i in range(total_frames):
        img = blank_canvas()
        draw_wave_frame(img, i, expr_name="happy")
        driver.show(img)
        time.sleep(frame_dur)
    time.sleep(SLEEP_DELAY_S)
    if sleep_fn:
        sleep_fn()


# ============================================================
# Legacy direct events (pre-BLE era)
# ============================================================

LEGACY_EVENTS = {
    "feed":  ("happy",    2.5, {"fullness": +30}),
    "pet":   ("love",     2.8, {"love":     +25}),
    "play":  ("excited",  2.8, {"love": +12, "energy": -8}),
    "sleep": ("sleeping", 5.0, {"energy":   +35}),
    "speak": ("singing",  2.8, {}),
    "poke":  (None,       1.8, {}),
}

def random_poke():
    return random.choice(["surprised", "shocked", "dizzy", "mad", "silly", "wink"])


# ============================================================
# Main loop
# ============================================================

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--driver", choices=["luma", "waveshare", "preview"], default="luma")
    ap.add_argument("--fps",   type=float, default=10.0)
    ap.add_argument("--decay", type=float, default=1.0,
                    help="Stat decay speed multiplier. 1.0 = realistic.")
    ap.add_argument("--once",  default=None,
                    help="Render a single expression once and exit.")
    args = ap.parse_args()

    driver = make_driver(args.driver)

    # ── Single-expression preview mode ────────────────────────────────────────
    if args.once:
        if args.once not in EXPRESSIONS:
            print(f"unknown expression: {args.once}")
            print("available:", ", ".join(EXPRESSIONS))
            sys.exit(1)
        img = blank_canvas()
        draw_face(img, args.once)
        driver.show(img)
        print(f"Showed {args.once}. (Ctrl-C to exit.)")
        try:
            while True: time.sleep(1)
        except KeyboardInterrupt: pass
        driver.close()
        return

    # ── Load persistent state ─────────────────────────────────────────────────
    state = EvaState.load()
    state.update_mood()
    state.save_phone_view()

    # ── Live loop variables ───────────────────────────────────────────────────
    expr_name  = state.mood
    hold_until = 0.0
    next_blink = time.time() + random.uniform(3, 6)
    next_look  = time.time() + random.uniform(6, 10)
    look_until = 0.0
    look       = (0, 0)
    breathe_phase = 0
    last_decay    = time.time()
    last_save     = time.time()

    # BLE state
    ble_connected = False
    phone_expr    = None    # last mood from phone; drives OLED when connected

    # Media mode
    media_mode  = 'none'   # 'none' | 'music' | 'video'
    media_frame = 0

    # PIN pairing
    pin_mode       = False
    display_pin    = ''
    pin_frame      = 0
    pin_fail_until = 0.0

    def cleanup(*_):
        state.save()
        driver.close()
        sys.exit(0)
    signal.signal(signal.SIGINT,  cleanup)
    signal.signal(signal.SIGTERM, cleanup)

    frame_period = 1.0 / args.fps
    print(f"EVA Pixel Pal running. BLE events via {EVENT_FILE}")

    while True:
        t0  = time.time()
        now = t0

        # ── 1) Stat decay ─────────────────────────────────────────────────────
        dt_decay = now - last_decay
        if dt_decay >= frame_period:
            apply_decay(state, dt_decay, speed=args.decay)
            last_decay = now

        # Periodic save + phone-view push (every 8 s)
        if now - last_save >= 8.0:
            state.update_mood()
            state.save()
            state.save_phone_view()
            last_save = now

        # ── 2) Drain + process events ─────────────────────────────────────────
        for ev in drain_events():
            parts   = ev.split(' ', 2)
            keyword = parts[0]

            # ── BLE connect ───────────────────────────────────────────────────
            if keyword == 'ble_connect':
                ble_connected = True
                expr_name  = "excited"
                hold_until = now + 2.5

            # ── PIN events ────────────────────────────────────────────────────
            elif keyword == 'ble_pin_show':
                display_pin    = parts[1] if len(parts) > 1 else '------'
                pin_mode       = True
                pin_frame      = 0
                pin_fail_until = 0.0

            elif keyword == 'ble_pin_ok':
                pin_mode    = False
                display_pin = ''
                expr_name   = "happy"
                hold_until  = now + 2.0

            elif keyword == 'ble_pin_skip':
                pin_mode    = False
                display_pin = ''

            elif keyword == 'ble_pin_fail':
                pin_fail_until = now + 1.5

            # ── BLE disconnect ────────────────────────────────────────────────
            elif keyword == 'ble_disconnect':
                ble_connected  = False
                pin_mode       = False
                display_pin    = ''
                pin_fail_until = 0.0
                media_mode     = 'none'
                media_frame    = 0
                phone_expr     = None

                def go_sleep():
                    nonlocal expr_name, hold_until
                    expr_name  = "sleeping"
                    hold_until = now + 999

                play_wave_goodbye(driver, sleep_fn=go_sleep)

            # ── Proximity ─────────────────────────────────────────────────────
            elif keyword == 'ble_proximity':
                level = parts[1] if len(parts) > 1 else 'medium'
                if ble_connected and now >= hold_until:
                    if level == 'close':  expr_name = phone_expr or 'happy'
                    elif level == 'far':  expr_name = 'sleepy'

            # ── Mood from phone (OLED sync only — Pi ignores stat payload) ────
            elif keyword == 'ble_mood':
                mood_str = parts[1] if len(parts) > 1 else 'neutral'
                phone_expr = MOOD_EXPR_MAP.get(mood_str, 'neutral')
                expr_name  = phone_expr
                hold_until = now + 0.5

            # ── Activity (Pi applies effects + picks OLED expression) ─────────
            elif keyword in ('ble_activity', 'ble_game'):
                atype = parts[1] if len(parts) > 1 else ''
                score = 1.0
                if len(parts) > 2:
                    try:
                        score = float(json.loads(parts[2]).get('score', 1.0))
                    except Exception:
                        pass
                if atype:
                    deltas = apply_activity(state, atype, score, now=now)
                    state.update_mood()
                    state.save()
                    state.save_phone_view()
                    print(f"  activity={atype} score={score:.2f} deltas={deltas}")
                    expr_info = get_activity_expr(atype)
                    if expr_info:
                        expr_name, hold_s = expr_info
                        hold_until = now + hold_s

            # ── Prefs (no visual reaction) ────────────────────────────────────
            elif keyword == 'ble_prefs':
                pass

            # ── Generic BLE command ───────────────────────────────────────────
            elif keyword == 'ble_cmd':
                try:
                    payload = json.loads(parts[1]) if len(parts) > 1 else {}
                except Exception:
                    payload = {}

                cmd = payload.get('cmd', '')

                if cmd == 'media':
                    new_mode = payload.get('state', 'none')
                    if new_mode != media_mode:
                        media_mode  = new_mode
                        media_frame = 0
                        if media_mode == 'music':
                            expr_name = 'singing'; hold_until = now + 1.5
                        elif media_mode == 'video':
                            expr_name = 'excited'; hold_until = now + 1.5
                        else:
                            hold_until = 0.0

                elif cmd == 'revive':
                    state.revive()
                    expr_name  = 'happy'
                    hold_until = now + 3.0
                    pin_mode   = False
                    print("  EVA revived!")

            # ── Legacy events ─────────────────────────────────────────────────
            elif keyword in LEGACY_EVENTS:
                target, hold, delta = LEGACY_EVENTS[keyword]
                for k, v in delta.items():
                    if hasattr(state.stats, k):
                        setattr(state.stats, k,
                                max(0.0, min(100.0, getattr(state.stats, k) + v)))
                if keyword == "poke":
                    target = random_poke()
                expr_name  = target or expr_name
                hold_until = now + hold

            else:
                print(f"  unknown event: {ev}")

        # ── 3) Drift toward ambient when hold expires ─────────────────────────
        if now >= hold_until:
            if not ble_connected:
                want = "sleeping"
            elif phone_expr is not None:
                want = phone_expr
            else:
                want = ambient_mood(state.stats)
            if want != expr_name:
                expr_name = want

        # ── 4) Blink ──────────────────────────────────────────────────────────
        blink = 0.0
        if expr_name not in ("sleeping", "closed") and now > next_blink:
            t_into = now - next_blink
            if t_into < 0.04:   blink = 0.5
            elif t_into < 0.08: blink = 1.0
            elif t_into < 0.12: blink = 0.5
            else: next_blink = now + random.uniform(3, 6)

        # ── 5) Look ───────────────────────────────────────────────────────────
        if now > next_look and look_until == 0.0:
            look = (random.choice([-2, -1, 0, 1, 2]),
                    random.choice([-1, 0, 0, 0, 1]))
            look_until = now + random.uniform(0.8, 1.5)
        elif now > look_until and look_until > 0.0:
            look = (0, 0)
            look_until = 0.0
            next_look  = now + random.uniform(6, 10)

        # ── 6) Breathe ────────────────────────────────────────────────────────
        breathe_phase = int(now * 1.4) % 4
        cy_offset     = -1 if breathe_phase == 1 else (1 if breathe_phase == 3 else 0)

        # ── 7) Render ─────────────────────────────────────────────────────────
        img = blank_canvas()
        if pin_mode:
            if now < pin_fail_until:
                draw_face(img, "mad")
            else:
                draw_pin_frame(img, display_pin, pin_frame)
                pin_frame += 1
        elif media_mode == 'music':
            draw_music_frame(img, media_frame)
            media_frame += 1
        elif media_mode == 'video':
            draw_video_frame(img, media_frame)
            media_frame += 1
        else:
            draw_face(img, expr_name,
                      cy=16 + cy_offset,
                      blink=blink,
                      global_look=look)
        driver.show(img)

        # ── 8) Pace ───────────────────────────────────────────────────────────
        dt = time.time() - t0
        if dt < frame_period:
            time.sleep(frame_period - dt)


if __name__ == "__main__":
    main()
