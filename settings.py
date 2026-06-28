"""
Layered settings for DoesTheDogWatchPlex.

Resolution order for every setting (first hit wins):

    1. environment variable        (great for Docker / stack deploys)
    2. settings.json               (what the GUI reads & writes)
    3. config.py                   (legacy / manual setups)
    4. the schema default          (defined below)

`SCHEMA` is the single source of truth: the engine reads values through `get()`,
and the GUI builds its form straight from this list, so the two never drift.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

# Data dir holds settings.json (+ the .cache used by dtdd.py). Override with
# DTDD_DATA_DIR to point at a mounted volume in Docker.
DATA_DIR = Path(os.environ.get("DTDD_DATA_DIR") or Path(__file__).parent)
SETTINGS_FILE = DATA_DIR / "settings.json"

# Optional legacy config.py — fine if it doesn't exist.
try:
    import config as _config
except Exception:
    _config = None


# --- Schema -----------------------------------------------------------------
# Each entry: key, label, type, default, group, help, and optional flags.
# type ∈ {str, text, password, int, float, bool, list, multichoice, choice}
#   - list:        a list of free-text strings (e.g. topic names, library names)
#   - multichoice: a list constrained to `choices`
#   - choice:      a single value from `choices`
SCHEMA = [
    # --- Connection ---
    {"key": "PLEX_URL", "label": "Plex URL", "type": "str",
     "default": "http://localhost:32400", "group": "Connection",
     "help": "Your Plex server address, including port."},
    {"key": "PLEX_TOKEN", "label": "Plex token", "type": "password",
     "default": "", "group": "Connection", "secret": True,
     "help": "X-Plex-Token. Plex web → play media → inspect a request for it."},
    {"key": "DTDD_API_KEY", "label": "DoesTheDogDie API key", "type": "password",
     "default": "", "group": "Connection", "secret": True,
     "help": "Sign up at doesthedogdie.com, then copy the key from your profile."},

    # --- Libraries ---
    {"key": "PLEX_LIBRARY_TYPES", "label": "Library types", "type": "multichoice",
     "default": ["movies"], "choices": ["movies", "tv_shows"],
     "choice_labels": {"movies": "Movies", "tv_shows": "TV Shows"}, "group": "Libraries",
     "help": "Which kinds of library to process."},
    {"key": "PLEX_LIBRARIES", "label": "Library names", "type": "list",
     "default": None, "group": "Libraries",
     "help": "Specific library names (must match the type above). Empty = all matching libraries."},
    {"key": "TV_WARNING_LEVELS", "label": "TV warning levels", "type": "multichoice",
     "default": ["series", "season", "episode"],
     "choices": ["series", "season", "episode"],
     "choice_labels": {"series": "Series", "season": "Season", "episode": "Episode"},
     "group": "Libraries",
     "help": "Which levels to write for TV. Episode = one API call per episode (slow on big libraries)."},

    # --- Filtering ---
    {"key": "MIN_YES_VOTES", "label": "Minimum 'yes' votes", "type": "int",
     "default": 5, "group": "Filtering",
     "help": "Drop warnings with fewer than this many 'yes' votes."},
    {"key": "MIN_YES_RATIO", "label": "Minimum yes ratio", "type": "float",
     "default": 0.7, "group": "Filtering",
     "help": "Require yes / (yes + no) to be at least this (0–1)."},
    {"key": "SHOW_SAFE_TOPICS", "label": "Show ✅ safe topics", "type": "bool",
     "default": False, "group": "Filtering",
     "help": "Also list things the community says do NOT happen (e.g. 'no dogs die')."},
    {"key": "INCLUDE_TOPICS", "label": "Only these topics", "type": "list",
     "default": None, "group": "Filtering",
     "help": "If set, ONLY these topics appear. Overrides the exclude list."},
    {"key": "EXCLUDE_TOPICS", "label": "Hide these topics", "type": "list",
     "default": None, "group": "Filtering",
     "help": "Hide these topics. Ignored when an include list is set."},
    {"key": "LANGUAGE", "label": "Translate to language", "type": "str",
     "default": None, "group": "Filtering",
     "help": "Language code to translate topic names into (e.g. es, fr, de, ja). Blank = English."},

    # --- Appearance (how the warning block looks in Plex) ---
    {"key": "WARNING_LAYOUT", "label": "Layout", "type": "choice",
     "default": "inline", "choices": ["inline", "lines", "categorized"],
     "choice_labels": {"inline": "All on one line", "lines": "One per line",
                       "categorized": "Grouped by category"},
     "group": "Appearance",
     "help": "How warnings are arranged in the summary."},
    {"key": "USE_CATEGORY_ICONS", "label": "Category emoji (categorized layout)", "type": "bool",
     "default": True, "group": "Appearance",
     "help": "Prefix each category with an emoji (🐾 Animal Death, 🔪 Violence…) in the grouped layout."},
    {"key": "SHOW_TIMESTAMPS", "label": "Show timestamps", "type": "bool",
     "default": True, "group": "Appearance",
     "help": "Append the first scene time to each warning, e.g. 'a dog dies (0:14:38)'. "
             "Needs a DoesTheDogDie subscription + a title with submitted timecodes; "
             "silently does nothing otherwise."},
    {"key": "SHOW_CUES", "label": "Show skip cues (look-away → safe)", "type": "bool",
     "default": False, "group": "Appearance",
     "help": "Show the skip-to range instead of just the time, e.g. "
             "'a dog dies (0:14:38 → 0:16:21)' — when to look away and when it's safe."},
    {"key": "SEPARATOR", "label": "Header line", "type": "text",
     "default": "\n\n———— Content Warnings (via DoesTheDogDie.com) ————",
     "group": "Appearance",
     "help": "Divider/header inserted before the warnings. Leading blank lines space it from the summary."},
    {"key": "WARN_PREFIX", "label": "Warning prefix", "type": "str",
     "default": "⚠️  ", "group": "Appearance",
     "help": "Text/emoji before the list of things that DO happen."},
    {"key": "SAFE_PREFIX", "label": "Safe prefix", "type": "str",
     "default": "✅  ", "group": "Appearance",
     "help": "Text/emoji before the ✅ safe list (only used if 'Show safe topics' is on)."},
    {"key": "TOPIC_DELIMITER", "label": "Topic separator", "type": "str",
     "default": " · ", "group": "Appearance",
     "help": "Joins topics within a line."},

    # --- Advanced ---
    {"key": "API_DELAY", "label": "API delay (seconds)", "type": "float",
     "default": 1.0, "group": "Advanced",
     "help": "Pause between DoesTheDogDie API calls. Be kind to their server."},
    {"key": "CACHE_TTL", "label": "Cache lifetime (seconds)", "type": "int",
     "default": 604800, "group": "Advanced",
     "help": "How long to reuse cached API responses. Default 7 days."},
    {"key": "DRY_RUN", "label": "Dry run by default", "type": "bool",
     "default": False, "group": "Advanced",
     "help": "Preview changes without writing to Plex."},
]

_BY_KEY = {entry["key"]: entry for entry in SCHEMA}

# In-memory cache of settings.json, so get() doesn't hit disk every call.
_json_cache: dict | None = None


def _load_json() -> dict:
    global _json_cache
    if _json_cache is None:
        if SETTINGS_FILE.exists():
            try:
                _json_cache = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                _json_cache = {}
        else:
            _json_cache = {}
    return _json_cache


def _coerce(value: str, type_: str):
    """Coerce a string (from an env var) into the schema type."""
    if type_ == "bool":
        return value.strip().lower() in ("1", "true", "yes", "on")
    if type_ == "int":
        try:
            return int(value)
        except ValueError:
            return None
    if type_ == "float":
        try:
            return float(value)
        except ValueError:
            return None
    if type_ in ("list", "multichoice"):
        return [v.strip() for v in value.split(",") if v.strip()]
    return value


def get(key: str, default=None):
    """Resolve a setting through env → settings.json → config.py → schema default."""
    spec = _BY_KEY.get(key, {})
    type_ = spec.get("type", "str")

    # 1. environment variable
    if key in os.environ and os.environ[key] != "":
        return _coerce(os.environ[key], type_)

    # 2. settings.json (presence is authoritative, even if the value is null)
    data = _load_json()
    if key in data:
        return data[key]

    # 3. legacy config.py
    if _config is not None and hasattr(_config, key):
        return getattr(_config, key)

    # 4. schema default, then caller-supplied default
    if "default" in spec:
        return spec["default"]
    return default


def all_settings() -> dict:
    """Current resolved value of every schema key (for the GUI to render)."""
    return {entry["key"]: get(entry["key"]) for entry in SCHEMA}


def load_saved() -> dict:
    """Raw contents of settings.json (only keys the user has explicitly saved)."""
    return dict(_load_json())


def save(values: dict):
    """Write the given key→value map to settings.json and refresh the cache.

    Only schema keys are persisted; unknown keys are ignored.
    """
    global _json_cache
    clean = {k: v for k, v in values.items() if k in _BY_KEY}
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    SETTINGS_FILE.write_text(json.dumps(clean, indent=2, ensure_ascii=False), encoding="utf-8")
    _json_cache = clean


def stage(values: dict):
    """Apply values in memory only (no disk write), so the engine sees current
    GUI field values during Test/Dry-run/Run before the user commits with Save.
    """
    global _json_cache
    _json_cache = {k: v for k, v in values.items() if k in _BY_KEY}


def reload():
    """Drop the in-memory cache (next get() re-reads settings.json)."""
    global _json_cache
    _json_cache = None
