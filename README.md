# DoesTheDogWatchPlex

Add content warnings from [DoesTheDogDie.com](https://www.doesthedogdie.com) to your Plex **movie and TV** summaries — so anyone browsing your library can see trigger warnings without leaving the Plex interface.

Rebuilt from [valknight/DoesTheDogWatchPlex](https://github.com/valknight/DoesTheDogWatchPlex) (2018) for modern Plex and the current DTDD API, then extended with TV show support (series / season / episode levels).

## What It Does

For each **movie** in your Plex library, the script:

1. Matches it to DoesTheDogDie.com (by IMDB ID first, then title/year)
2. Fetches community-voted content warnings (animal death, sexual assault, etc.)
3. Appends a formatted warning block to the movie's summary in Plex

The result looks like this in Plex:

```
Original movie summary here...

———— Content Warnings (via DoesTheDogDie.com) ————
⚠️  a dog dies · an animal is sad · someone is buried alive
✅  no cats die · nobody is stalked
```

Warnings are filtered by vote count and confidence ratio, so you only see things the community is reasonably sure about.

## TV Shows

TV libraries get warnings at up to three levels, each written to the matching Plex summary (configurable via `TV_WARNING_LEVELS`):

| Level | Written to | DTDD lookup |
|---|---|---|
| `series` | the show summary | whole-series community votes |
| `season` | each season summary | `index1=<season>, index2=-1` |
| `episode` | each episode summary | `index1=<season>, index2=<episode>` |

The show is matched **once** (by IMDB id, then title+year against `TV Show` results) to resolve its DTDD id; season and episode warnings then come from DTDD's own per-index aggregates — authoritative data computed server-side, not a filtered sample of the series page.

> **A note on episode/season accuracy.** DTDD's per-index data is community-sourced and uneven. Most topics are correctly scoped, but a chunk of **series-wide** votes get attributed to the **first season and first episode** (DTDD's default bucket for votes cast without a specific index). So *Season 1* and *S1E1* of a show tend to over-report — they inherit some warnings that really apply to the whole series — while later seasons/episodes are clean. For example, Game of Thrones Season 1 returns 13 topics while Seasons 2–6 return ~1 each. This is a DTDD data quirk, not a matching bug, and it can't be cleanly auto-stripped without risking genuine warnings (e.g. a pet that really does die in episode 1). The series level is the most complete; treat S1/S1E1 as approximate. See the [Roadmap](#roadmap) for planned mitigations.

Episode level makes one API call per episode, so it's the slowest option across a large library — start with `series` + `season` and add `episode` once you're happy with the output.

## The App (GUI)

If you'd rather not touch a config file or the command line, there's a friendly app — a clickable window with a setup screen that walks you through pasting your Plex and DoesTheDogDie keys, a searchable picker for the ~200 content topics, live preview of how the warning will look, and buttons for **Dry-run**, **Run**, and **Clear**.

```bash
pip install -r requirements-gui.txt

python gui.py          # opens as a desktop window (no port to manage)
python gui.py --web    # serves a web app instead — for Docker / stack use
```

The same window runs as a **desktop app** locally and as a **web app** for a server stack (set `DTDD_GUI_PORT`, default `8550`). It saves your choices to `settings.json`, which the engine and CLI also read — so the GUI, command line, and Docker stay in sync.

**Run the web GUI in Docker** (`Dockerfile.gui`):

```bash
docker build -f Dockerfile.gui -t dtdd-gui .
docker run -d -p 8550:8550 -v dtdd-data:/data \
  -e PLEX_URL=http://YOUR_PLEX_IP:32400 -e PLEX_TOKEN=xxx -e DTDD_API_KEY=xxx \
  dtdd-gui
```

`DTDD_DATA_DIR=/data` holds `settings.json` + the API cache (mount a volume to persist them). Env vars seed the connection on first boot; everything else is set in the UI. Put it behind a reverse proxy / SSO if you expose it — it holds your Plex token and writes to Plex.

> Handy for TV: set a **single show** in the action bar to add episode-level warnings one series at a time, instead of hammering the API across your whole library at once.

The aesthetic is a deliberately loud retrofuturist / vaporwave / cyberpunk theme — broadly themed, not tied to any one server.

## Setup

### Docker (recommended)

```bash
git clone https://github.com/justkorix/DoesTheDogWatchPlex.git
cd DoesTheDogWatchPlex
```

Edit `docker-compose.yml` with your Plex URL, token, and DTDD API key, then:

```bash
# Preview first
docker compose run --rm doesthedogwatchplex --dry-run

# Run once
docker compose run --rm doesthedogwatchplex

# Run as a background service (re-scans every 24h by default)
docker compose up -d
```

Or run directly with `docker run`:

```bash
docker run --rm \
  -e PLEX_URL=http://YOUR_PLEX_IP:32400 \
  -e PLEX_TOKEN=your-plex-token \
  -e DTDD_API_KEY=your-dtdd-api-key \
  -v dtdd-cache:/app/.cache \
  ghcr.io/justkorix/doesthedogwatchplex --dry-run
```

Set `SCHEDULE=86400` to re-scan every 24 hours, or omit it to run once and exit.

### Manual (no Docker)

**Prerequisites:** Python 3.7+, a Plex server, a DoesTheDogDie.com account.

```bash
# Clone or copy the files to your server
cd ~/DoesTheDogWatchPlex

# Create a virtual environment (no sudo needed)
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Configure
cp config.py.example config.py
# Edit config.py with your Plex URL, token, and DTDD API key
```

### Getting Your Credentials

**Plex Token:** Open Plex in a browser, play any media, and inspect network requests for the `X-Plex-Token` parameter. Or see [Plex's guide](https://support.plex.tv/articles/204059436-finding-an-authentication-token-x-plex-token/).

**DTDD API Key:** Create an account at [doesthedogdie.com](https://www.doesthedogdie.com/signup), then visit your [profile page](https://www.doesthedogdie.com/profile) to find your API key.

## Usage

```bash
# Activate venv first
source venv/bin/activate

# Preview what would change (safe, doesn't modify Plex)
python plex_warnings.py --dry-run

# Run it for real
python plex_warnings.py

# Process a single movie
python plex_warnings.py --movie "Midsommar"

# Process a single TV show (series/season/episode per TV_WARNING_LEVELS)
python plex_warnings.py --show "Game of Thrones"

# Remove all content warnings from your library (movies + all TV levels)
python plex_warnings.py --clear

# Clear the local API cache (forces fresh DTDD lookups)
python plex_warnings.py --clear-cache

# List all available topic names for filtering
python plex_warnings.py --list-topics
```

### Running on a Schedule (cron)

To automatically process new additions:

```bash
crontab -e
```

Add a line like this to run nightly at 3am:

```
0 3 * * * cd ~/DoesTheDogWatchPlex && venv/bin/python plex_warnings.py >> dtdd.log 2>&1
```

## Configuration

All settings are in `config.py`. Key options:

| Setting | Env Var | Default | Description |
|---|---|---|---|
| `PLEX_LIBRARY_TYPES` | `PLEX_LIBRARY_TYPES` | `["movies"]` | Kinds of library to process: `"movies"`, `"tv_shows"` |
| `PLEX_LIBRARIES` | `PLEX_LIBRARIES` | `["Movies"]` | Which named libraries to process (filtered by type). `None` = all matching `PLEX_LIBRARY_TYPES` |
| `TV_WARNING_LEVELS` | `TV_WARNING_LEVELS` | `["series","season","episode"]` | For TV: which levels to write. Drop `"episode"` for far fewer API calls |
| `MIN_YES_VOTES` | `MIN_YES_VOTES` | `5` | Minimum "yes" votes to include a warning |
| `MIN_YES_RATIO` | `MIN_YES_RATIO` | `0.7` | Minimum ratio of yes/(yes+no) to flag a warning |
| `SHOW_SAFE_TOPICS` | `SHOW_SAFE_TOPICS` | `False` | Include the ✅ "safe" list (e.g., "no dogs die") |
| `INCLUDE_TOPICS` | `INCLUDE_TOPICS` | `None` | Only show these topics (comma-separated). Overrides EXCLUDE_TOPICS |
| `EXCLUDE_TOPICS` | `EXCLUDE_TOPICS` | `None` | Hide these topics (comma-separated). Ignored if INCLUDE_TOPICS is set |
| `LANGUAGE` | `LANGUAGE` | `None` | Translate warnings to another language (e.g., `es`, `fr`, `de`, `pt`, `ja`) |
| `API_DELAY` | - | `1.0` | Seconds between DTDD API calls |
| `CACHE_TTL` | - | `604800` | Cache duration in seconds (default: 7 days) |
| `DRY_RUN` | `DRY_RUN` | `False` | Set to `True` to preview without writing |
| - | `SCHEDULE` | - | Docker only: seconds between re-runs (e.g., `86400` for daily) |

## Topic Filtering

You can control which topics appear in your warnings using `INCLUDE_TOPICS` and `EXCLUDE_TOPICS`. Both use the plain English topic names from DoesTheDogDie.com (not numeric IDs). Matching is case-insensitive.

To see every available topic name, run:

```bash
python plex_warnings.py --list-topics
```

This prints all ~200 topics in a copy-paste-ready format. Example output:

```
Available topics from DoesTheDogDie.com:
  - a dog dies
  - a cat dies
  - an animal is sad
  - someone is sexually assaulted
  - there are bugs
  ...
```

**Only show specific topics you care about:**

```python
# config.py
INCLUDE_TOPICS = ["a dog dies", "a cat dies", "someone is sexually assaulted"]
```

```yaml
# docker-compose.yml
INCLUDE_TOPICS=a dog dies,a cat dies,someone is sexually assaulted
```

**Hide topics you don't want to see:**

```python
# config.py
EXCLUDE_TOPICS = ["there is copaganda", "there are shower scenes"]
```

```yaml
# docker-compose.yml
EXCLUDE_TOPICS=there is copaganda,there are shower scenes
```

If both are set, `INCLUDE_TOPICS` takes priority and `EXCLUDE_TOPICS` is ignored.

## How It Works

- **Matching:** Tries IMDB ID first (via Plex's GUID metadata), then falls back to title+year search against the DTDD API. TV shows match once at the series level to resolve a DTDD id, then use indexed lookups for seasons/episodes.
- **Caching:** API responses are cached locally in `.cache/` as JSON files to avoid hammering DTDD on re-runs.
- **Idempotent:** Safe to re-run. Existing warnings are stripped and replaced with fresh data each time, at every level (movie / series / season / episode).
- **Reversible:** `--clear` removes all DTDD-added content from summaries, restoring originals.

## Roadmap

- ✅ **GUI for settings & topic selection** — desktop window + web app (`gui.py`); see [The App](#the-app-gui).
- **Packaged installers** — pre-built `.exe` / `.dmg` / `.AppImage` via `flet build`, so non-technical users can just download and double-click (no Python).
- **One-click web service** — a `docker-compose` service for the web GUI behind the stack.
- **Smarter episode/season attribution** — mitigate DTDD's tendency to dump series-wide votes onto Season 1 / S1E1 (see the accuracy note above), e.g. by cross-referencing later episodes to spot topics that are uniform across an entire show.
- **Per-library configuration** — different thresholds or topic filters per Plex library.

## Credits

- Original concept: [valknight/DoesTheDogWatchPlex](https://github.com/valknight/DoesTheDogWatchPlex) (2018).
- TV show support drew on community work toward the same goal, including [greghesp's `feature/tv-show-support`](https://github.com/greghesp/DoesTheDogWatchPlex/tree/feature/tv-show-support) branch.
- Content warning data: the [DoesTheDogDie.com](https://www.doesthedogdie.com) community.

> Built with the help of [Claude Code](https://claude.com/claude-code) (Anthropic Claude Opus 4.8).

## License

MIT — see [LICENSE](LICENSE). This is a derivative work; the original project is MIT-licensed and that notice is retained.
