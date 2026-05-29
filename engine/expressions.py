"""Maps activity types → (OLED expression, hold_seconds) and computes ambient mood."""
from __future__ import annotations
from typing import Optional, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    from .state import Stats

# activity_type → (expr_name, hold_s)
ACTIVITY_EXPRESSIONS: dict[str, Tuple[str, float]] = {
    # Food
    'feed_start':    ('hungry',    1.5),
    'feed_done':     ('happy',     2.5),
    'feed_cancel':   ('neutral',   1.0),
    'cook_start':    ('singing',   2.0),
    'cook_success':  ('excited',   2.5),
    'cook_burned':   ('sad',       2.0),
    'cook_raw':      ('shocked',   1.8),
    'eat':           ('happy',     2.0),
    'use_item':      ('happy',     2.0),
    # Hygiene
    'wash_start':    ('shocked',   1.5),
    'wash_done':     ('giggle',    2.5),
    'wash_cancel':   ('neutral',   1.0),
    # Rest
    'rest_start':    ('sleepy',    2.5),
    'rest_done':     ('happy',     2.5),
    'rest_cancel':   ('yawn',      1.5),
    # Entertainment
    'cinema_start':  ('excited',   2.0),
    'cinema_done':   ('sleepy',    2.5),
    'stars_done':    ('excited',   2.5),
    'reaction_done': ('excited',   2.0),
    # Exercise
    'gym_start':     ('surprised', 1.5),
    'gym_done':      ('happy',     2.5),
    # Shopping
    'market_buy':    ('giggle',    1.5),
    # Games — *_done events are cosmetic (reward comes via play_done); these
    # just give the OLED a fitting reaction.
    'memory_done':   ('love',      2.0),
    'balon_done':    ('excited',   2.5),
    'hizlimat_done': ('happy',     2.0),
    'colormatch_done':('excited',  2.0),
    'colormatch_start':('curious', 1.2),
    'pitch_done':    ('excited',   2.0),
    'pitch_start':   ('curious',   1.2),
    'rhythm_done':   ('singing',   2.0),
    'rhythm_start':  ('excited',   1.2),
    'simon_done':    ('giggle',    2.0),
    'simon_start':   ('curious',   1.2),
    'play_start':    ('excited',   1.8),
    'play_done':     ('excited',   2.5),
    'play_cancel':   ('sad',       1.5),
}

# phone mood string → OLED expression name
MOOD_EXPR_MAP: dict[str, str] = {
    'happy':   'happy',
    'sad':     'sad',
    'sleepy':  'sleepy',
    'excited': 'excited',
    'hungry':  'hungry',
    'angry':   'angry',
    'neutral': 'neutral',
    'idle':    'idle',
}


def get_activity_expr(activity: str) -> Optional[Tuple[str, float]]:
    """Return (expr_name, hold_s) for a given activity, or None."""
    return ACTIVITY_EXPRESSIONS.get(activity)


def ambient_mood(stats: 'Stats') -> str:
    """Derive current mood from stat values."""
    if stats.energy      < 15: return 'sleepy'
    if stats.energy      < 30: return 'yawn'
    if stats.fullness    < 20: return 'hungry'
    if stats.cleanliness < 25: return 'sad'
    if stats.love        < 20: return 'sad'
    if stats.love        > 85: return 'happy'
    if stats.energy      > 85 and stats.fullness > 60: return 'idle'
    return 'neutral'
