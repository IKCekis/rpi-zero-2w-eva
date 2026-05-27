"""EvaState — persistent stats, meta, and activity history.  Pi is the single
source of truth for all game numbers; the mobile app only displays them.
"""
from __future__ import annotations
import json
import time
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Dict, List

# /run is a fast tmpfs; backup in home dir survives reboots.
STATE_FILE  = Path('/run/pal.state.json')
BACKUP_FILE = Path('/home/ikcekis/pal/eva_state.json')
# Compact phone-facing view that ble_server polls and pushes via STATE_CHAR.
PHONE_FILE  = Path('/run/pal.phone.json')


@dataclass
class Stats:
    fullness:    float = 75.0   # "hunger" on mobile
    love:        float = 60.0   # "happiness"
    energy:      float = 90.0
    cleanliness: float = 80.0   # "clean"
    health:      float = 70.0


@dataclass
class Meta:
    money:              float = 100.0
    level:              int   = 1
    xp:                 float = 0.0
    age_days:           float = 0.0
    born_at:            float = field(default_factory=time.time)
    total_interactions: int   = 0


@dataclass
class EvaState:
    stats:        Stats                  = field(default_factory=Stats)
    meta:         Meta                   = field(default_factory=Meta)
    activity_log: Dict[str, List[float]] = field(default_factory=dict)
    mood:         str                    = 'neutral'

    # ── Persistence ──────────────────────────────────────────────────────────

    def save(self) -> None:
        data = {
            'stats':        asdict(self.stats),
            'meta':         asdict(self.meta),
            'activity_log': self.activity_log,
            'mood':         self.mood,
        }
        text = json.dumps(data)
        try: STATE_FILE.write_text(text)
        except Exception: pass
        try: BACKUP_FILE.write_text(json.dumps(data, indent=2))
        except Exception: pass

    def save_phone_view(self) -> None:
        """Write compact JSON for ble_server to push via STATE_CHAR notify."""
        try:
            PHONE_FILE.write_text(json.dumps(self.to_phone_json()))
        except Exception:
            pass

    @classmethod
    def load(cls) -> 'EvaState':
        for path in (STATE_FILE, BACKUP_FILE):
            try:
                data = json.loads(path.read_text())
                return cls(
                    stats=Stats(**data.get('stats', {})),
                    meta=Meta(**data.get('meta', {})),
                    activity_log=data.get('activity_log', {}),
                    mood=data.get('mood', 'neutral'),
                )
            except Exception:
                continue
        return cls()

    # ── Helpers ───────────────────────────────────────────────────────────────

    def log_activity(self, activity: str, now: float | None = None) -> None:
        now = now or time.time()
        log = self.activity_log.setdefault(activity, [])
        log.append(now)
        self.activity_log[activity] = log[-20:]

    def update_mood(self) -> None:
        from .expressions import ambient_mood
        self.mood = ambient_mood(self.stats)

    def is_dead(self) -> bool:
        s = self.stats
        return s.fullness <= 0 and s.love <= 0 and s.energy <= 0

    def to_phone_json(self) -> dict:
        return {
            'stats': {
                'fullness':    round(self.stats.fullness,    1),
                'love':        round(self.stats.love,        1),
                'energy':      round(self.stats.energy,      1),
                'cleanliness': round(self.stats.cleanliness, 1),
                'health':      round(self.stats.health,      1),
            },
            'meta': {
                'money':    round(self.meta.money,    1),
                'level':    self.meta.level,
                'xp':       round(self.meta.xp,       1),
                'age_days': round(self.meta.age_days, 2),
            },
            'mood': self.mood,
        }

    def revive(self) -> None:
        self.stats   = Stats(fullness=50, love=50, energy=50, cleanliness=60, health=50)
        self.meta.xp = 0.0
        self.mood    = 'happy'
        self.save()
        self.save_phone_view()
