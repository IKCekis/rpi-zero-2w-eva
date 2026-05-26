"""
main.py — Pixel Pal main loop for Raspberry Pi (EVA edition).

Handles BLE events pushed by ble_server.py via /tmp/pal.events:

  ble_connect                  — phone came close → wake animation
  ble_disconnect               → wave goodbye, then sleep after a delay
  ble_proximity <level>        — level = close|medium|far
  ble_mood <mood> <stats_json> — update expression from phone activity
  ble_activity <type> <json>   — react to specific activities
  ble_game <type> <json>       — react to game outcomes
  ble_prefs <json>             — store prefs (no visual reaction needed)

Legacy events (still supported):
  feed, pet, play, sleep, speak, poke

Usage on Pi:
    sudo python3 main.py --driver luma

Quick desktop test:
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
    blank_canvas, draw_face, draw_wave_frame, EXPRESSIONS, W, H,
)


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
# Tamagotchi stats
# ============================================================

def clamp(v, lo=0.0, hi=100.0):
    return max(lo, min(hi, v))


def ambient(stats):
    if stats["energy"] < 15:   return "sleepy"
    if stats["energy"] < 30:   return "yawn"
    if stats["fullness"] < 20: return "hungry"
    if stats["love"] < 20:     return "sad"
    if stats["love"] > 85:     return "happy"
    if stats["energy"] > 85 and stats["fullness"] > 60: return "idle"
    return "neutral"


# Legacy simple events
LEGACY_EVENTS = {
    "feed":  ("happy",     2.5, {"fullness": +30}),
    "pet":   ("love",      2.8, {"love": +25}),
    "play":  ("excited",   2.8, {"love": +12, "energy": -8}),
    "sleep": ("sleeping",  5.0, {"energy": +35}),
    "speak": ("singing",   2.8, {}),
    "poke":  (None,        1.8, {}),
}

# Map phone mood strings → expressions
MOOD_TO_EXPR = {
    "happy":   "happy",
    "sad":     "sad",
    "sleepy":  "sleepy",
    "excited": "excited",
    "hungry":  "hungry",
    "angry":   "angry",
    "neutral": "neutral",
    "idle":    "idle",
}

# Map activity types → (expression, hold_s)
ACTIVITY_TO_EXPR = {
    "eat":          ("happy",   2.0),
    "cook_success": ("excited", 2.5),
    "cook_burned":  ("sad",     2.0),
    "cinema_start": ("excited", 2.0),
    "cinema_done":  ("sleepy",  2.5),
    "gym_start":    ("surprised", 1.5),
    "gym_done":     ("happy",   2.5),
    "market_buy":   ("giggle",  1.5),
    "stars_done":   ("excited", 2.5),
    "reaction_done":("excited", 2.0),
    "memory_done":  ("love",    2.0),
    "balon_done":   ("excited", 2.5),
    "hizlimat_done":("happy",   2.0),
}


def random_poke():
    return random.choice(["surprised", "shocked", "dizzy", "mad", "silly", "wink"])


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
    return [line.strip() for line in content.splitlines() if line.strip()]


# ============================================================
# Wave animation — play N cycles then transition to sleeping
# ============================================================

WAVE_CYCLES   = 3       # 3 × 12 frames = 36 frames of waving
WAVE_FPS      = 12      # faster for the animation
SLEEP_DELAY_S = 3.0     # after wave, delay before switching to sleeping


def play_wave_goodbye(driver, sleep_fn=None):
    """Block for WAVE_CYCLES × 12 frames then optionally call sleep_fn."""
    frame_dur = 1.0 / WAVE_FPS
    total_frames = WAVE_CYCLES * 12
    for i in range(total_frames):
        img = blank_canvas()
        draw_wave_frame(img, i, expr_name="happy")
        driver.show(img)
        time.sleep(frame_dur)
    # Pause, then sleep
    time.sleep(SLEEP_DELAY_S)
    if sleep_fn:
        sleep_fn()


# ============================================================
# Main loop
# ============================================================

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--driver", choices=["luma", "waveshare", "preview"], default="luma")
    ap.add_argument("--fps",   type=float, default=10.0)
    ap.add_argument("--decay", type=float, default=1.0,
                    help="Stat decay multiplier. 1.0 = realistic.")
    ap.add_argument("--once",  default=None,
                    help="Render a single expression and exit.")
    args = ap.parse_args()

    driver = make_driver(args.driver)

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

    # ── Live loop state ────────────────────────────────────────────────
    stats = {"fullness": 75.0, "love": 60.0, "energy": 90.0}
    expr_name  = "neutral"
    hold_until = 0.0
    next_blink = time.time() + random.uniform(3, 6)
    next_look  = time.time() + random.uniform(6, 10)
    look_until = 0.0
    look       = (0, 0)
    breathe_phase = 0
    last_decay = time.time()

    # BLE state
    ble_connected  = False
    wave_pending   = False
    wave_done_at   = 0.0

    def cleanup(*_):
        driver.close()
        sys.exit(0)
    signal.signal(signal.SIGINT, cleanup)
    signal.signal(signal.SIGTERM, cleanup)

    frame_period = 1.0 / args.fps

    print(f"EVA Pixel Pal running. BLE events via {EVENT_FILE}")

    while True:
        t0  = time.time()
        now = t0

        # 1) Decay stats
        if now - last_decay > 1.5 / args.decay:
            stats["fullness"] = clamp(stats["fullness"] - 0.6)
            stats["love"]     = clamp(stats["love"]     - 0.4)
            stats["energy"]   = clamp(stats["energy"]   - 0.3)
            last_decay = now

        # 2) Drain + process events
        for ev in drain_events():
            parts = ev.split(' ', 2)
            keyword = parts[0]

            # ── BLE connect ───────────────────────────────────────────
            if keyword == 'ble_connect':
                ble_connected = True
                wave_pending  = False
                expr_name  = "excited"
                hold_until = now + 2.5

            # ── BLE disconnect ────────────────────────────────────────
            elif keyword == 'ble_disconnect':
                ble_connected = False
                # Play wave animation inline (blocks the loop ~4 s).
                def go_sleep():
                    nonlocal expr_name, hold_until
                    expr_name  = "sleeping"
                    hold_until = now + 999  # stay asleep until reconnect

                play_wave_goodbye(driver, sleep_fn=go_sleep)
                # After returning, loop continues with sleeping state.

            # ── Proximity ─────────────────────────────────────────────
            elif keyword == 'ble_proximity':
                level = parts[1] if len(parts) > 1 else 'medium'
                if level == 'close' and ble_connected:
                    # Already connected and close — stay happy
                    if now >= hold_until:
                        expr_name = "happy"
                elif level == 'far' and ble_connected:
                    # Phone moved away but still technically connected
                    if now >= hold_until:
                        expr_name = "sleepy"

            # ── Mood from phone ───────────────────────────────────────
            elif keyword == 'ble_mood':
                mood_str = parts[1] if len(parts) > 1 else 'neutral'
                phone_expr = MOOD_TO_EXPR.get(mood_str, 'neutral')
                # Update love/fullness/energy from stats JSON if provided
                if len(parts) > 2:
                    try:
                        phone_stats = json.loads(parts[2])
                        if 'hunger' in phone_stats:
                            stats['fullness'] = clamp(phone_stats['hunger'])
                        if 'happiness' in phone_stats:
                            stats['love'] = clamp(phone_stats['happiness'])
                        if 'energy' in phone_stats:
                            stats['energy'] = clamp(phone_stats['energy'])
                    except Exception:
                        pass
                expr_name  = phone_expr
                hold_until = now + 1.5

            # ── Activity reaction ─────────────────────────────────────
            elif keyword == 'ble_activity':
                atype = parts[1] if len(parts) > 1 else ''
                if atype in ACTIVITY_TO_EXPR:
                    target_expr, hold_s = ACTIVITY_TO_EXPR[atype]
                    expr_name  = target_expr
                    hold_until = now + hold_s

            # ── Game reaction ─────────────────────────────────────────
            elif keyword == 'ble_game':
                gtype = parts[1] if len(parts) > 1 else ''
                if gtype in ACTIVITY_TO_EXPR:
                    target_expr, hold_s = ACTIVITY_TO_EXPR[gtype]
                    expr_name  = target_expr
                    hold_until = now + hold_s

            # ── Prefs (no visual reaction needed) ─────────────────────
            elif keyword == 'ble_prefs':
                pass  # stored by ble_server.py already

            # ── Legacy events ─────────────────────────────────────────
            elif keyword in LEGACY_EVENTS:
                target, hold, delta = LEGACY_EVENTS[keyword]
                for k, v in delta.items():
                    stats[k] = clamp(stats[k] + v)
                if keyword == "poke":
                    target = random_poke()
                expr_name  = target or expr_name
                hold_until = now + hold

            else:
                print(f"  unknown event: {ev}")

        # 3) Drift to ambient if not held and connected
        if now >= hold_until:
            want = "sleeping" if not ble_connected else ambient(stats)
            if want != expr_name:
                expr_name = want

        # 4) Blink
        blink = 0.0
        if expr_name not in ("sleeping", "closed") and now > next_blink:
            t_into = now - next_blink
            if t_into < 0.04:    blink = 0.5
            elif t_into < 0.08:  blink = 1.0
            elif t_into < 0.12:  blink = 0.5
            else:
                next_blink = now + random.uniform(3, 6)

        # 5) Look
        if now > next_look and look_until == 0.0:
            look = (random.choice([-2, -1, 0, 1, 2]),
                    random.choice([-1, 0, 0, 0, 1]))
            look_until = now + random.uniform(0.8, 1.5)
        elif now > look_until and look_until > 0.0:
            look = (0, 0)
            look_until = 0.0
            next_look  = now + random.uniform(6, 10)

        # 6) Breathe
        breathe_phase = int(now * 1.4) % 4
        cy_offset = -1 if breathe_phase == 1 else (1 if breathe_phase == 3 else 0)

        # 7) Render
        img = blank_canvas()
        draw_face(img, expr_name,
                  cy=16 + cy_offset,
                  blink=blink,
                  global_look=look)
        driver.show(img)

        # 8) Pace
        dt = time.time() - t0
        if dt < frame_period:
            time.sleep(frame_period - dt)


if __name__ == "__main__":
    main()
