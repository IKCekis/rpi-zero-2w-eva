"""Activity effect engine: diminishing returns, variety bonuses, neglect amplification.

Design principles
-----------------
* Same activity group repeated within 2 hours → each instance cuts effectiveness by 35 %
* Not done in 20+ hours → 1.6× variety bonus
* Consecutive neglect (stat already low) → faster decay
* Game outcomes scale effects via a 0–1 score
"""
from __future__ import annotations
import time
from typing import Dict, List, TYPE_CHECKING

if TYPE_CHECKING:
    from .state import EvaState

# ── Base stat deltas per activity (before effectiveness multiplier) ────────────
# Keys: fullness / love / energy / cleanliness / health (mapped to Stats fields)
#       money (Meta.money, NOT multiplied — cost is always full)
#       xp    (Meta.xp,   IS multiplied by effectiveness)

ACTIVITY_BASE: Dict[str, Dict[str, float]] = {
    # Feeding
    'feed_done':      {'fullness': +26.0, 'love': +4.0,  'health': +2.0,   'xp': +3.0},
    'cook_success':   {'fullness': +30.0, 'love': +12.0, 'health': +5.0,   'money': -15.0, 'xp': +8.0},
    'cook_burned':    {'fullness': +5.0,  'love': -8.0,                     'money': -15.0, 'xp': +1.0},
    'eat':            {'fullness': +20.0, 'love': +6.0,                     'xp': +1.0},
    # Hygiene
    'wash_done':      {'love': +14.0, 'energy': +4.0, 'cleanliness': +30.0, 'health': +3.0, 'xp': +4.0},
    # Rest
    'rest_done':      {'energy': +35.0, 'fullness': -4.0, 'xp': +2.0},
    # Entertainment — must diversify (same group → diminish)
    'cinema_done':    {'love': +18.0, 'energy': -8.0,  'xp': +5.0},
    'stars_done':     {'love': +14.0, 'energy': -5.0,  'xp': +4.0},
    'reaction_done':  {'love': +10.0, 'energy': -4.0,  'xp': +3.0},
    # Exercise
    'gym_done':       {'energy': -14.0, 'love': +22.0, 'fullness': -10.0, 'health': +12.0, 'xp': +9.0},
    # Shopping
    'market_buy':     {'love': +8.0,  'money': -10.0, 'xp': +2.0},
    # Games — outcome-weighted via score param
    'memory_done':    {'love': +10.0, 'energy': -5.0,  'xp': +6.0},
    'balon_done':     {'love': +8.0,  'energy': -4.0,  'xp': +4.0},
    'hizlimat_done':  {'love': +12.0, 'energy': -6.0,  'xp': +6.0},
    # Play generic
    'play_done':      {'love': +14.0, 'energy': -8.0,  'xp': +4.0},
}

# Activities competing in the same variety "slot"
ACTIVITY_GROUPS: Dict[str, str] = {
    'cinema_done':    'entertainment',
    'stars_done':     'entertainment',
    'reaction_done':  'entertainment',
    'memory_done':    'games',
    'balon_done':     'games',
    'hizlimat_done':  'games',
    'play_done':      'games',
    'feed_done':      'food',
    'cook_success':   'food',
    'cook_burned':    'food',
    'eat':            'food',
    'wash_done':      'hygiene',
    'rest_done':      'rest',
    'gym_done':       'exercise',
    'market_buy':     'shopping',
}

# Tuning constants
SAME_GROUP_WINDOW_H   = 2.0   # hours — repeated group use in this window diminishes
VARIETY_BONUS_AFTER_H = 20.0  # hours — long break before activity → bonus
DIMINISH_PER_USE      = 0.65  # multiply effectiveness by this for each recent group use
DIMINISH_FLOOR        = 0.15  # minimum effectiveness multiplier
XP_PER_LEVEL          = 100.0
MONEY_LEVEL_UP        = 20.0  # bonus coins on level-up

# Decay rates: stat points lost per second at nominal pace
_DECAY_RATES = {
    'fullness':    0.40 / 90,   # ~100 → 0 in 250 s at x1.0 (use --decay to tune)
    'love':        0.25 / 90,
    'energy':      0.20 / 90,
    'cleanliness': 0.15 / 90,
    'health':      0.10 / 90,
}


# ── Effectiveness calculation ─────────────────────────────────────────────────

def _group_recent(group: str, log: Dict[str, List[float]], now: float) -> int:
    """Count uses of any activity in group within SAME_GROUP_WINDOW_H hours."""
    cutoff = now - SAME_GROUP_WINDOW_H * 3600
    return sum(
        1 for act, grp in ACTIVITY_GROUPS.items()
        if grp == group
        for t in log.get(act, [])
        if t > cutoff
    )


def _hours_since(activity: str, log: Dict[str, List[float]], now: float) -> float:
    times = log.get(activity, [])
    return (now - max(times)) / 3600 if times else float('inf')


def effectiveness(activity: str, log: Dict[str, List[float]], now: float) -> float:
    """Return multiplier ∈ [DIMINISH_FLOOR, 1.6] for this activity."""
    group = ACTIVITY_GROUPS.get(activity)
    if group:
        recent = _group_recent(group, log, now)
    else:
        cutoff = now - SAME_GROUP_WINDOW_H * 3600
        recent = sum(1 for t in log.get(activity, []) if t > cutoff)

    diminish = max(DIMINISH_FLOOR, DIMINISH_PER_USE ** recent)

    gap_h = _hours_since(activity, log, now)
    if gap_h > VARIETY_BONUS_AFTER_H:
        variety = 1.6
    elif gap_h > VARIETY_BONUS_AFTER_H / 2:
        variety = 1.25
    else:
        variety = 1.0

    return diminish * variety


# ── Apply activity ────────────────────────────────────────────────────────────

def apply_activity(state: 'EvaState', activity: str,
                   score: float = 1.0, now: float | None = None) -> Dict[str, float]:
    """
    Apply activity effects to EvaState.

    score: 0.0–1.0 game outcome (1.0 = perfect). Money costs are always full.
    Returns actual stat deltas applied (for logging/feedback).
    """
    now = now or time.time()
    base = ACTIVITY_BASE.get(activity, {})
    mult = effectiveness(activity, state.activity_log, now) * max(0.0, min(1.0, score))

    applied: Dict[str, float] = {}
    for key, delta in base.items():
        if key == 'xp':
            gained = delta * mult
            state.meta.xp += gained
            applied['xp'] = round(gained, 2)
        elif key == 'money':
            state.meta.money = max(0.0, state.meta.money + delta)
            applied['money'] = delta
        else:
            if hasattr(state.stats, key):
                old = getattr(state.stats, key)
                new_val = max(0.0, min(100.0, old + delta * mult))
                setattr(state.stats, key, new_val)
                applied[key] = round(new_val - old, 2)

    # Level ups
    while state.meta.xp >= XP_PER_LEVEL:
        state.meta.xp -= XP_PER_LEVEL
        state.meta.level += 1
        state.meta.money += MONEY_LEVEL_UP

    state.log_activity(activity, now)
    state.meta.total_interactions += 1
    return applied


# ── Stat decay ────────────────────────────────────────────────────────────────

def apply_decay(state: 'EvaState', dt_seconds: float, speed: float = 1.0) -> None:
    """
    Decay stats over dt_seconds at the given speed multiplier.

    Neglect amplification: stats already below 30 decay faster.
    """
    for key, rate in _DECAY_RATES.items():
        val = getattr(state.stats, key)
        amp = 2.0 if val < 15 else (1.5 if val < 30 else 1.0)
        setattr(state.stats, key, max(0.0, val - rate * dt_seconds * speed * amp))

    state.meta.age_days += dt_seconds / 86400
