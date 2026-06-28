#!/usr/bin/env python3
"""
DoesTheDogWatchPlex — Content warnings from DoesTheDogDie.com in your Plex library.

Usage:
    python plex_warnings.py              # Process all configured libraries
    python plex_warnings.py --dry-run    # Preview changes without writing
    python plex_warnings.py --clear      # Remove all content warnings from Plex
    python plex_warnings.py --clear-cache  # Clear the local DTDD API cache
    python plex_warnings.py --movie "Midsommar"  # Process a single movie by title
    python plex_warnings.py --show "Game of Thrones"  # Process a single TV show
    python plex_warnings.py --list-topics  # Show all available topic names for filtering

TV shows get warnings at three levels (configurable via TV_WARNING_LEVELS):
    series  → written to the show summary (whole-series community votes)
    season  → written to each season summary (DTDD index1=<season>, index2=-1)
    episode → written to each episode summary (DTDD index1=<season>, index2=<episode>)
"""
from __future__ import annotations

import argparse
import sys
import time

from plexapi.server import PlexServer

from dtdd import DTDDClient
import settings

# Maps PLEX_LIBRARY_TYPES strings to Plex internal section type names
_LIBRARY_TYPE_MAP = {
    "movies": "movie",
    "tv_shows": "show",
}

# Default TV levels if not configured
_DEFAULT_TV_LEVELS = ["series", "season", "episode"]

# Emoji per DoesTheDogDie topic category, used by the "categorized" warning layout.
# Anything not listed falls back to FALLBACK_CATEGORY_ICON.
FALLBACK_CATEGORY_ICON = "⚠️"
CATEGORY_ICONS = {
    "Abandonment": "🚪", "Abuse": "💢", "Addiction": "🍷",
    "Animal Death": "🐾", "Animal Distress": "🐾", "Animal Phobia": "🕷️",
    "Appendages": "✋", "Assault": "👊", "Children": "🧒",
    "Creepy Crawly": "🐛", "Death": "💀", "Disability": "♿",
    "Drugs/Alcohol": "💊", "Family": "👪", "Fear": "😱", "Gross": "🤢",
    "Head": "🧠", "LGBTQ+": "🏳️‍🌈", "Large-scale Violence": "💥",
    "Law Enforcement": "🚓", "Loss": "💔", "Medical": "🏥",
    "Mental Health": "🫥", "Natural Disasters": "🌪️", "Neck": "🩸",
    "Noxious": "⚡", "Paranoia": "👁️", "Pregnancy": "🤰",
    "Prejudice": "✊", "Race": "✊", "Relationships": "💔",
    "Religious": "✝️", "Self Harm": "🩸", "Sex": "❤️‍🔥", "Sexism": "♀️",
    "Sexual Assault": "🚫", "Sickness": "🤒", "Social": "👥", "Spoiler": "🔒",
    "Vehicular": "🚗", "Violence": "🔪", "Whole Body": "🩹",
}


def get_separator() -> str:
    return settings.get("SEPARATOR")


def strip_warnings(summary: str) -> str:
    """Remove existing DTDD content warnings from a summary."""
    sep = get_separator()
    if sep in summary:
        return summary.split(sep)[0].rstrip()
    # Also handle the old-style separator from the original project
    if "\ndoesthedogdie:" in summary.lower():
        for i, line in enumerate(summary.split("\n")):
            if line.strip().lower().startswith("doesthedogdie:"):
                return "\n".join(summary.split("\n")[:i]).rstrip()
    return summary


def media_id(media_data: dict | None) -> int | None:
    """Return the DTDD media id from a /media payload.

    The id lives at media_data["item"]["id"]; older/search payloads may put it
    at the top level. Returns None if neither is present.
    """
    if not isinstance(media_data, dict):
        return None
    item = media_data.get("item")
    if isinstance(item, dict) and item.get("id"):
        return item["id"]
    return media_data.get("id")


def _evaluate_warnings(media_data: dict) -> tuple[list[dict], list[dict]]:
    """Apply thresholds + topic filters. Returns (yes, no) lists of dicts:
    {name, category, stat} — `name` is the warning's display name (notName for the
    'safe' list), `stat` is the raw topicItemStat (for context comments).
    """
    stats = media_data.get("topicItemStats", [])
    if not stats:
        return [], []

    min_yes = settings.get("MIN_YES_VOTES")
    min_ratio = settings.get("MIN_YES_RATIO")
    show_nos = settings.get("SHOW_SAFE_TOPICS")
    include_topics = settings.get("INCLUDE_TOPICS")
    exclude_topics = settings.get("EXCLUDE_TOPICS")
    inc = [t.lower() for t in include_topics] if include_topics else None
    exc = [t.lower() for t in exclude_topics] if exclude_topics else None

    yes, no = [], []
    for stat in stats:
        yes_count = stat.get("yesSum", 0)
        no_count = stat.get("noSum", 0)
        total = yes_count + no_count
        topic = stat.get("topic", {})
        topic_name = topic.get("name", "")
        category = (topic.get("TopicCategory") or {}).get("name") or "Other"

        if total == 0 or not topic_name:
            continue
        if inc is not None:
            if topic_name.lower() not in inc:
                continue
        elif exc is not None:
            if topic_name.lower() in exc:
                continue

        ratio = yes_count / total
        if ratio >= min_ratio and yes_count >= min_yes:
            yes.append({"name": topic_name, "category": category, "stat": stat})
        elif show_nos and (1 - ratio) >= min_ratio and no_count >= min_yes:
            no.append({"name": topic.get("notName", ""), "category": category, "stat": stat})
    return yes, no


def timeline_map(entries: list[dict]) -> dict[str, list[dict]]:
    """Index timeline entries by lowercased topic name -> [entries] (in order)."""
    out: dict[str, list[dict]] = {}
    for e in entries or []:
        key = (e.get("topic") or "").strip().lower().rstrip(".")
        if key:
            out.setdefault(key, []).append(e)
    return out


def build_item_timeline(dtdd: DTDDClient, media_data: dict) -> dict[str, list[dict]]:
    """Fetch + index the timeline for a media payload, if it has timecodes and
    timestamps/cues are enabled. Returns {} when there's nothing to fetch."""
    if not (settings.get("SHOW_TIMESTAMPS") or settings.get("SHOW_CUES")):
        return {}
    if not media_data.get("itemTimecodeCount"):
        return {}
    mid = media_id(media_data)
    if not mid:
        return {}
    try:
        return timeline_map(dtdd.get_timeline(mid))
    except Exception:
        return {}


def _time_suffix(entries: list[dict] | None) -> str:
    """' (start)' or ' (start → end)' for a topic's first timeline entry."""
    if not entries:
        return ""
    e = entries[0]
    start, end = e.get("start"), e.get("end")
    if settings.get("SHOW_CUES") and start and end:
        return f" ({start} → {end})"
    if settings.get("SHOW_TIMESTAMPS") and start:
        return f" ({start})"
    if settings.get("SHOW_CUES") and start:
        return f" ({start})"
    return ""


def format_warnings(media_data: dict, timeline: dict | None = None,
                    descriptions: dict | None = None) -> str | None:
    """Extract and format trigger warnings from DTDD media response.

    timeline:     {topic_lower: [timeline entries]} — adds timestamps/cues per setting.
    descriptions: {topic_lower: [detail lines]} — selected scene/community description
                  lines (review screen). Placed right under their topic so that, in the
                  categorized layout, a topic's descriptions sit under its category.
    Returns a formatted string of warnings, or None if no relevant warnings found.
    """
    warnings_yes, warnings_no = _evaluate_warnings(media_data)
    if not warnings_yes and not warnings_no:
        return None

    # Translate topic names if LANGUAGE is configured
    target_lang = settings.get("LANGUAGE")
    if target_lang:
        from translate import translate_topics
        all_names = [w["name"] for w in warnings_yes] + [w["name"] for w in warnings_no]
        trans = translate_topics(all_names, target_lang)
    else:
        trans = None

    def label_of(w):
        """Translated name + timestamp/cue suffix (from the timeline, if any)."""
        name = trans[w["name"]] if trans else w["name"]
        if timeline:
            name += _time_suffix(timeline.get(w["name"].lower()))
        return name

    descriptions = descriptions or {}

    def desc_lines(w):
        return descriptions.get(w["name"].lower(), [])

    layout = settings.get("WARNING_LAYOUT")
    use_icons = settings.get("USE_CATEGORY_ICONS")
    warn_prefix = settings.get("WARN_PREFIX")
    safe_prefix = settings.get("SAFE_PREFIX")
    delimiter = settings.get("TOPIC_DELIMITER")

    def render(items, prefix):
        """items: list of {name, category}. Render per the configured layout,
        placing each topic's selected descriptions right under it."""
        if not items:
            return []
        out = []
        if layout == "lines":
            for w in items:
                out.append(f"{prefix}{label_of(w)}")
                out.extend(desc_lines(w))
        elif layout == "categorized":
            groups: dict[str, list] = {}
            for w in items:
                groups.setdefault(w["category"], []).append(w)
            for cat in sorted(groups):
                icon = (CATEGORY_ICONS.get(cat, FALLBACK_CATEGORY_ICON) + " ") if use_icons else ""
                out.append(f"{icon}{cat}: " + delimiter.join(label_of(w) for w in groups[cat]))
                for w in groups[cat]:        # descriptions sit under their category
                    out.extend(desc_lines(w))
        else:  # inline (default) — descriptions follow the single line
            out.append(prefix + delimiter.join(label_of(w) for w in items))
            for w in items:
                out.extend(desc_lines(w))
        return out

    lines = render(warnings_yes, warn_prefix) + render(warnings_no, safe_prefix)
    return "\n".join(lines)


def extract_contexts(media_data: dict, index1=None, index2=None) -> list[dict]:
    """For each passing warning topic, return its top community comment as context.

    Returns [{topic, category, comment, votes}], best comment first. If index1/2 are
    given (season/episode), prefer comments tagged to that episode.
    """
    yes, _ = _evaluate_warnings(media_data)
    out = []
    for w in yes:
        comments = w["stat"].get("comments") or []
        if index1 is not None:
            scoped = [c for c in comments
                      if c.get("index1") == index1 and (index2 is None or c.get("index2") == index2)]
            comments = scoped or comments
        comments = [c for c in comments if (c.get("comment") or "").strip()]
        if not comments:
            continue
        top = max(comments, key=lambda c: c.get("voteSum", 0))
        out.append({"topic": w["name"], "category": w["category"],
                    "comment": top["comment"].strip(), "votes": top.get("voteSum", 0)})
    out.sort(key=lambda c: -c["votes"])
    return out


def apply_warnings(item, media_data: dict | None, label: str, dry_run: bool = False,
                   indent: str = "  ", timeline: dict | None = None,
                   descriptions: dict | None = None) -> bool:
    """Format warnings from media_data and write them to item.summary.

    Strips any existing DTDD block first (idempotent). Returns True if warnings
    were added (or would be, in dry-run).
    """
    warning_text = (format_warnings(media_data, timeline=timeline, descriptions=descriptions)
                    if media_data else None)
    if not warning_text:
        print(f"{indent}– {label} — no significant warnings")
        return False

    original = getattr(item, "summary", "") or ""
    new_summary = strip_warnings(original) + get_separator() + "\n" + warning_text

    if dry_run:
        print(f"{indent}✓ {label} — would add warnings:")
        for line in warning_text.split("\n"):
            print(f"{indent}    {line}")
        return True

    try:
        item.editSummary(new_summary)
        print(f"{indent}✓ {label} — warnings added")
        return True
    except Exception as e:
        print(f"{indent}✗ {label} — failed to update: {e}")
        return False


def _extract_external_ids(item) -> dict[str, str]:
    """Extract known external IDs from a Plex item's guids.

    Returns a dict with any of: 'imdb', 'tvdb'.
    """
    ids = {}
    try:
        for guid in item.guids:
            if guid.id.startswith("imdb://"):
                ids["imdb"] = guid.id.replace("imdb://", "")
            elif guid.id.startswith("tvdb://"):
                ids["tvdb"] = guid.id.replace("tvdb://", "")
    except Exception:
        pass
    return ids


def match_movie(dtdd: DTDDClient, movie) -> dict | None:
    """Match a Plex movie to a DTDD entry.

    Strategy: IMDb id first (most reliable), then title+year, then first Movie result.
    Returns the DTDD media data dict, or None.
    """
    title = movie.title
    year = movie.year
    ext_ids = _extract_external_ids(movie)

    if "imdb" in ext_ids:
        results = dtdd.search_by_imdb(ext_ids["imdb"])
        if results:
            return dtdd.get_media(results[0]["id"])

    results = dtdd.search(title)
    if not results:
        return None

    if year:
        for item in results:
            if str(year) == str(item.get("releaseYear", "")):
                return dtdd.get_media(item["id"])

    for item in results:
        if item.get("itemType", {}).get("name", "") == "Movie":
            return dtdd.get_media(item["id"])

    return dtdd.get_media(results[0]["id"])


def process_movie(dtdd: DTDDClient, movie, dry_run: bool = False) -> bool:
    """Process a single movie. Returns True if the summary was updated."""
    title = f"{movie.title} ({movie.year})" if movie.year else movie.title

    try:
        media_data = match_movie(dtdd, movie)
    except Exception as e:
        print(f"  ✗ {title} — API error: {e}")
        return False

    if not media_data:
        print(f"  – {title} — not found on DTDD")
        return False

    timeline = build_item_timeline(dtdd, media_data)
    return apply_warnings(movie, media_data, title, dry_run=dry_run, indent="  ", timeline=timeline)


def match_show(dtdd: DTDDClient, show) -> dict | None:
    """Match a Plex show to DTDD and return its full (series-level) media data.

    Strategy: IMDb id first, then title search restricted to itemType 'TV Show'
    (matching on release year when possible). Returns the full media payload
    (carries the DTDD id used for per-season / per-episode lookups), or None.
    """
    ext_ids = _extract_external_ids(show)

    if "imdb" in ext_ids:
        results = dtdd.search_by_imdb(ext_ids["imdb"])
        if results:
            return dtdd.get_media(results[0]["id"])

    results = dtdd.search(show.title)
    if not results:
        return None

    tv_results = [r for r in results if r.get("itemType", {}).get("name") == "TV Show"]

    if show.year:
        for item in tv_results:
            if str(show.year) == str(item.get("releaseYear", "")):
                return dtdd.get_media(item["id"])

    if tv_results:
        return dtdd.get_media(tv_results[0]["id"])

    return None


def iter_show_media(dtdd: DTDDClient, show, levels: list[str] | None = None):
    """Yield (plex_item, label, media_data, index1, index2) for each level of a show.

    Resolves the series once, then uses indexed /media lookups (authoritative,
    server-computed) for seasons and episodes. index1/index2 are None for the
    series, (season, -1) for a season, (season, episode) for an episode.
    """
    if levels is None:
        levels = _DEFAULT_TV_LEVELS

    series_media = match_show(dtdd, show)
    if not series_media:
        return
    show_id = media_id(series_media)

    if "series" in levels:
        yield (show, f"{show.title} — series", series_media, None, None)

    if not show_id or not ({"season", "episode"} & set(levels)):
        return

    for season in show.seasons():
        s_num = season.index
        if s_num is None:
            continue
        if "season" in levels:
            try:
                sm = dtdd.get_media(f"{show_id}?index1={s_num}&index2=-1")
            except Exception:
                sm = None
            if sm is not None:
                yield (season, f"{show.title} — Season {s_num:02d}", sm, s_num, -1)
        if "episode" in levels:
            try:
                episodes = season.episodes()
            except Exception:
                episodes = []
            for episode in episodes:
                e_num = episode.index
                if e_num is None:
                    continue
                try:
                    em = dtdd.get_media(f"{show_id}?index1={s_num}&index2={e_num}")
                except Exception:
                    em = None
                if em is not None:
                    label = f"{show.title} — S{s_num:02d}E{e_num:02d}"
                    if episode.title:
                        label += f" - {episode.title}"
                    yield (episode, label, em, s_num, e_num)


def process_show(dtdd: DTDDClient, show, dry_run: bool = False,
                 levels: list[str] | None = None) -> tuple[int, int]:
    """Process a TV show at the configured levels (series / season / episode).

    Returns (processed, updated) counts across all levels touched.
    """
    if levels is None:
        levels = _DEFAULT_TV_LEVELS

    print(f"  {show.title}")
    processed = 0
    updated = 0
    found = False
    try:
        for item, label, media, i1, i2 in iter_show_media(dtdd, show, levels):
            found = True
            short = label.split(" — ", 1)[-1]
            is_episode = i1 is not None and i2 is not None and i2 != -1
            indent = "      " if is_episode else "    "
            timeline = build_item_timeline(dtdd, media)
            processed += 1
            if apply_warnings(item, media, short, dry_run=dry_run, indent=indent, timeline=timeline):
                updated += 1
    except Exception as e:
        print(f"    ✗ API error: {e}")
        return processed, updated

    if not found:
        print("    – not found on DTDD")
    return processed, updated


def clear_warnings(plex: PlexServer, library_names: list[str] | None,
                   library_types: list[str] | None = None):
    """Remove all DTDD content warnings from library summaries (all levels)."""
    libraries = get_libraries(plex, library_names, library_types)
    total_cleared = 0

    def clear_item(item, label):
        nonlocal total_cleared
        original = getattr(item, "summary", "") or ""
        cleaned = strip_warnings(original)
        if cleaned != original:
            try:
                item.editSummary(cleaned)
                print(f"  ✓ {label} — warnings removed")
                total_cleared += 1
            except Exception:
                print(f"  ✗ {label} — failed to update")

    for lib in libraries:
        print(f"\nClearing warnings from: {lib.title}")
        if lib.type == "show":
            for show in lib.all():
                clear_item(show, show.title)
                for season in show.seasons():
                    clear_item(season, f"{show.title} — Season {season.index}")
                    try:
                        episodes = season.episodes()
                    except Exception:
                        episodes = []
                    for episode in episodes:
                        clear_item(episode, f"{show.title} S{season.index:02d}E{episode.index:02d}")
        else:
            for movie in lib.all():
                clear_item(movie, movie.title)

    print(f"\nDone. Cleared warnings from {total_cleared} item(s).")


def get_libraries(plex: PlexServer, library_names: list[str] | None,
                  library_types: list[str] | None = None):
    """Get libraries to process, filtered by type and optional name list."""
    if library_types is None:
        library_types = ["movies"]
    type_values = {_LIBRARY_TYPE_MAP[lt] for lt in library_types if lt in _LIBRARY_TYPE_MAP}

    if library_names:
        libraries = []
        for name in library_names:
            try:
                lib = plex.library.section(name)
                if lib.type in type_values:
                    libraries.append(lib)
                else:
                    print(f"Warning: '{name}' has type '{lib.type}', not in PLEX_LIBRARY_TYPES, skipping.")
            except Exception:
                print(f"Warning: Library '{name}' not found, skipping.")
        return libraries
    else:
        return [s for s in plex.library.sections() if s.type in type_values]


def make_client() -> DTDDClient:
    """Build a DTDD client from current settings."""
    return DTDDClient(
        api_key=settings.get("DTDD_API_KEY"),
        cache_ttl=settings.get("CACHE_TTL"),
        api_delay=settings.get("API_DELAY"),
    )


def connect_plex() -> PlexServer:
    """Connect to Plex using current settings (raises on failure)."""
    return PlexServer(settings.get("PLEX_URL"), settings.get("PLEX_TOKEN"))


def fetch_topics(dtdd: DTDDClient, sample_title: str = "Avengers Endgame") -> list[dict]:
    """Return every DTDD topic as {name, description, keywords}, sorted by name.

    Pulls them from a popular, heavily-rated title so the list is comprehensive.
    The description is handy as a tooltip in a topic picker.
    """
    results = dtdd.search(sample_title)
    if not results:
        return []
    media = dtdd.get_media(results[0]["id"])
    by_name: dict[str, dict] = {}
    for stat in media.get("topicItemStats", []):
        topic = stat.get("topic", {})
        name = topic.get("name")
        if not name or name in by_name:
            continue
        by_name[name] = {
            "name": name,
            "description": (topic.get("description") or "").strip(),
            "keywords": (topic.get("keywords") or "").strip(),
            "category": (topic.get("TopicCategory") or {}).get("name") or "Other",
        }
    return [by_name[n] for n in sorted(by_name)]


def fetch_topic_catalog(dtdd: DTDDClient, sample_title: str = "Avengers Endgame") -> list[str]:
    """Return every DTDD topic name (sorted) — names only, for the CLI."""
    return [t["name"] for t in fetch_topics(dtdd, sample_title)]


def main():
    parser = argparse.ArgumentParser(
        description="Add DoesTheDogDie.com content warnings to your Plex summaries."
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview changes without modifying Plex")
    parser.add_argument("--clear", action="store_true",
                        help="Remove all content warnings from Plex summaries")
    parser.add_argument("--clear-cache", action="store_true",
                        help="Clear the local DTDD API response cache")
    parser.add_argument("--movie", type=str,
                        help="Process a single movie by title (exact match)")
    parser.add_argument("--show", type=str,
                        help="Process a single TV show by title (exact match)")
    parser.add_argument("--list-topics", action="store_true",
                        help="Show all available DTDD topic names (for INCLUDE_TOPICS/EXCLUDE_TOPICS)")
    args = parser.parse_args()

    dry_run = args.dry_run or settings.get("DRY_RUN")
    tv_levels = settings.get("TV_WARNING_LEVELS")

    if not settings.get("DTDD_API_KEY"):
        print("ERROR: No DoesTheDogDie API key set.")
        print("Set it in settings.json / config.py, the DTDD_API_KEY env var, or the GUI.")
        sys.exit(1)

    # Handle cache clear
    if args.clear_cache:
        make_client().clear_cache()
        if not (args.clear or args.movie or args.show or args.list_topics):
            return

    # Handle list-topics
    if args.list_topics:
        print("Fetching topic list from DTDD...\n")
        topics = fetch_topic_catalog(make_client())
        if topics:
            print("Available topic names (copy these into INCLUDE_TOPICS or EXCLUDE_TOPICS):\n")
            for topic in topics:
                print(f'    "{topic}",')
            print(f"\n{len(topics)} topics found.")
        else:
            print("Could not fetch topics. Check your DTDD_API_KEY.")
        return

    # Connect to Plex
    print(f"Connecting to Plex at {settings.get('PLEX_URL')}...")
    try:
        plex = connect_plex()
        print(f"Connected to: {plex.friendlyName}")
    except Exception as e:
        print(f"ERROR: Could not connect to Plex: {e}")
        sys.exit(1)

    library_names = settings.get("PLEX_LIBRARIES")
    library_types = settings.get("PLEX_LIBRARY_TYPES")

    # Handle clear mode
    if args.clear:
        clear_warnings(plex, library_names, library_types)
        return

    dtdd = make_client()

    if dry_run:
        print("DRY RUN — no changes will be made to Plex\n")

    # Single movie
    if args.movie:
        libraries = get_libraries(plex, library_names, ["movies"])
        found = False
        for lib in libraries:
            for movie in lib.search(title=args.movie):
                found = True
                process_movie(dtdd, movie, dry_run=dry_run)
        if not found:
            print(f"Movie '{args.movie}' not found in Plex.")
        return

    # Single show
    if args.show:
        libraries = get_libraries(plex, library_names, ["tv_shows"])
        found = False
        for lib in libraries:
            for show in lib.search(title=args.show):
                found = True
                process_show(dtdd, show, dry_run=dry_run, levels=tv_levels)
        if not found:
            print(f"Show '{args.show}' not found in Plex.")
        return

    # Process all configured libraries
    libraries = get_libraries(plex, library_names, library_types)
    if not libraries:
        print("No libraries found to process. Check PLEX_LIBRARIES / PLEX_LIBRARY_TYPES.")
        sys.exit(1)

    print("Libraries to process:")
    for lib in libraries:
        item_label = "shows" if lib.type == "show" else "movies"
        print(f"  - {lib.title} ({len(lib.all())} {item_label})")
    print()

    total_processed = 0
    total_updated = 0
    start_time = time.time()

    for lib in libraries:
        items = lib.all()
        item_label = "shows" if lib.type == "show" else "movies"
        print(f"\nProcessing: {lib.title} ({len(items)} {item_label})")
        print("-" * 50)

        if lib.type == "show":
            for show in items:
                p, u = process_show(dtdd, show, dry_run=dry_run, levels=tv_levels)
                total_processed += p
                total_updated += u
        else:
            for movie in items:
                total_processed += 1
                if process_movie(dtdd, movie, dry_run=dry_run):
                    total_updated += 1

    elapsed = time.time() - start_time
    print(f"\n{'=' * 50}")
    print(f"Done in {elapsed:.1f}s")
    print(f"Processed: {total_processed} items")
    print(f"Updated:   {total_updated} items")
    if dry_run:
        print("(DRY RUN — no actual changes made)")


if __name__ == "__main__":
    main()
