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

try:
    import config
except ImportError:
    print("ERROR: config.py not found.")
    print("Copy config.py.example to config.py and fill in your details.")
    sys.exit(1)

# Maps PLEX_LIBRARY_TYPES strings to Plex internal section type names
_LIBRARY_TYPE_MAP = {
    "movies": "movie",
    "tv_shows": "show",
}

# Default TV levels if not configured
_DEFAULT_TV_LEVELS = ["series", "season", "episode"]


def get_separator() -> str:
    return getattr(config, "SEPARATOR", "\n\n———— Content Warnings (via DoesTheDogDie.com) ————")


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


def format_warnings(media_data: dict) -> str | None:
    """Extract and format trigger warnings from DTDD media response.

    Returns a formatted string of warnings, or None if no relevant warnings found.
    """
    stats = media_data.get("topicItemStats", [])
    if not stats:
        return None

    min_yes = getattr(config, "MIN_YES_VOTES", 3)
    min_ratio = getattr(config, "MIN_YES_RATIO", 0.6)

    show_nos = getattr(config, "SHOW_SAFE_TOPICS", False)
    include_topics = getattr(config, "INCLUDE_TOPICS", None)
    exclude_topics = getattr(config, "EXCLUDE_TOPICS", None)

    warnings_yes = []
    warnings_no = []

    for stat in stats:
        yes_count = stat.get("yesSum", 0)
        no_count = stat.get("noSum", 0)
        total = yes_count + no_count
        topic = stat.get("topic", {})
        topic_name = topic.get("name", "")
        topic_not_name = topic.get("notName", "")

        if total == 0 or not topic_name:
            continue

        # Apply topic filtering
        if include_topics is not None:
            if topic_name.lower() not in [t.lower() for t in include_topics]:
                continue
        elif exclude_topics is not None:
            if topic_name.lower() in [t.lower() for t in exclude_topics]:
                continue

        ratio = yes_count / total

        if ratio >= min_ratio and yes_count >= min_yes:
            warnings_yes.append((topic_name, yes_count, no_count))
        elif show_nos and (1 - ratio) >= min_ratio and no_count >= min_yes:
            warnings_no.append((topic_not_name, yes_count, no_count))

    if not warnings_yes and not warnings_no:
        return None

    # Translate topic names if LANGUAGE is configured
    target_lang = getattr(config, "LANGUAGE", None)
    if target_lang:
        from translate import translate_topics
        all_names = [w[0] for w in warnings_yes] + [w[0] for w in warnings_no]
        translations = translate_topics(all_names, target_lang)
    else:
        translations = None

    lines = []
    if warnings_yes:
        names = [translations[w[0]] if translations else w[0] for w in warnings_yes]
        lines.append("⚠️  " + " · ".join(names))
    if warnings_no:
        names = [translations[w[0]] if translations else w[0] for w in warnings_no]
        lines.append("✅  " + " · ".join(names))

    return "\n".join(lines)


def apply_warnings(item, media_data: dict | None, label: str, dry_run: bool = False,
                   indent: str = "  ") -> bool:
    """Format warnings from media_data and write them to item.summary.

    Strips any existing DTDD block first (idempotent). Returns True if warnings
    were added (or would be, in dry-run).
    """
    warning_text = format_warnings(media_data) if media_data else None
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

    return apply_warnings(movie, media_data, title, dry_run=dry_run, indent="  ")


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


def process_show(dtdd: DTDDClient, show, dry_run: bool = False,
                 levels: list[str] | None = None) -> tuple[int, int]:
    """Process a TV show at the configured levels (series / season / episode).

    Fetches the series once to resolve the DTDD id, then makes one indexed
    /media lookup per season and per episode (all cached locally). DTDD computes
    these per-index aggregates server-side, so the data is authoritative — not a
    filtered sample of the series payload.

    Returns (processed, updated) counts across all levels touched.
    """
    if levels is None:
        levels = _DEFAULT_TV_LEVELS

    print(f"  {show.title}")

    try:
        series_media = match_show(dtdd, show)
    except Exception as e:
        print(f"    ✗ API error: {e}")
        return 0, 0

    if not series_media:
        print(f"    – not found on DTDD")
        return 0, 0

    show_id = media_id(series_media)
    matched_name = series_media.get("item", {}).get("name", "unknown")
    print(f'    → matched: "{matched_name}" (DTDD id: {show_id})')

    processed = 0
    updated = 0

    # Series level
    if "series" in levels:
        processed += 1
        if apply_warnings(show, series_media, "series", dry_run=dry_run, indent="    "):
            updated += 1

    # Nothing more to do without an id or season/episode levels
    if not show_id or not ({"season", "episode"} & set(levels)):
        return processed, updated

    for season in show.seasons():
        s_num = season.index
        if s_num is None:
            continue

        if "season" in levels:
            processed += 1
            try:
                season_media = dtdd.get_media(f"{show_id}?index1={s_num}&index2=-1")
            except Exception as e:
                print(f"    ✗ Season {s_num:02d} — API error: {e}")
                season_media = None
            if season_media is not None:
                if apply_warnings(season, season_media, f"Season {s_num:02d}",
                                  dry_run=dry_run, indent="    "):
                    updated += 1

        if "episode" in levels:
            try:
                episodes = season.episodes()
            except Exception:
                episodes = []
            for episode in episodes:
                e_num = episode.index
                if e_num is None:
                    continue
                label = f"S{s_num:02d}E{e_num:02d}"
                if episode.title:
                    label += f" - {episode.title}"
                processed += 1
                try:
                    ep_media = dtdd.get_media(f"{show_id}?index1={s_num}&index2={e_num}")
                except Exception as e:
                    print(f"      ✗ {label} — API error: {e}")
                    ep_media = None
                if ep_media is not None:
                    if apply_warnings(episode, ep_media, label, dry_run=dry_run, indent="      "):
                        updated += 1

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

    dry_run = args.dry_run or getattr(config, "DRY_RUN", False)
    tv_levels = getattr(config, "TV_WARNING_LEVELS", _DEFAULT_TV_LEVELS)

    # Handle cache clear
    if args.clear_cache:
        client = DTDDClient(config.DTDD_API_KEY)
        client.clear_cache()
        if not (args.clear or args.movie or args.show or args.list_topics):
            return

    # Handle list-topics: fetch a well-known movie to show all available topics
    if args.list_topics:
        dtdd = DTDDClient(
            api_key=config.DTDD_API_KEY,
            cache_ttl=getattr(config, "CACHE_TTL", 604800),
            api_delay=getattr(config, "API_DELAY", 1.0),
        )
        print("Fetching topic list from DTDD...\n")
        results = dtdd.search("Avengers Endgame")
        if results:
            media = dtdd.get_media(results[0]["id"])
            stats = media.get("topicItemStats", [])
            topics = sorted(set(
                stat.get("topic", {}).get("name", "")
                for stat in stats
                if stat.get("topic", {}).get("name")
            ))
            print("Available topic names (copy these into INCLUDE_TOPICS or EXCLUDE_TOPICS):\n")
            for topic in topics:
                print(f'    "{topic}",')
            print(f"\n{len(topics)} topics found.")
        else:
            print("Could not fetch topics. Check your DTDD_API_KEY.")
        return

    # Connect to Plex
    print(f"Connecting to Plex at {config.PLEX_URL}...")
    try:
        plex = PlexServer(config.PLEX_URL, config.PLEX_TOKEN)
        print(f"Connected to: {plex.friendlyName}")
    except Exception as e:
        print(f"ERROR: Could not connect to Plex: {e}")
        sys.exit(1)

    library_names = getattr(config, "PLEX_LIBRARIES", None)
    library_types = getattr(config, "PLEX_LIBRARY_TYPES", None)

    # Handle clear mode
    if args.clear:
        clear_warnings(plex, library_names, library_types)
        return

    dtdd = DTDDClient(
        api_key=config.DTDD_API_KEY,
        cache_ttl=getattr(config, "CACHE_TTL", 604800),
        api_delay=getattr(config, "API_DELAY", 1.0),
    )

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
