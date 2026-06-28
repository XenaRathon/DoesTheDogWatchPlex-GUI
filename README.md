# DoesTheDogWatchPlex

Add community content warnings from [DoesTheDogDie.com](https://www.doesthedogdie.com) to your Plex **movie and TV** summaries — so anyone browsing your library sees trigger warnings without ever leaving the Plex interface.

```
Original summary here…

———— Content Warnings (via DoesTheDogDie.com) ————
🐾 Animal Death: a dog dies (0:14:38) · an animal is sad
🔪 Violence: someone is assaulted (0:57:34)
```

> 📖 **All setup, configuration, and usage live in the [Wiki](../../wiki).** This README only describes what the project is and what's new in this fork.

## 🍴 This is a fork

DoesTheDogWatchPlex started as [valknight/DoesTheDogWatchPlex](https://github.com/valknight/DoesTheDogWatchPlex) (2018) and was modernized by [justkorix/DoesTheDogWatchPlex](https://github.com/justkorix/DoesTheDogWatchPlex) for current Plex + the current DTDD API.

**This fork extends that further.** If you just want the original movies-only command-line tool, use the upstream repos — this one adds TV support, a full app, and live scene timecodes.

### ✨ What's new in this fork

- **📺 TV show support** — warnings at three levels (series / season / episode), each written to its own Plex summary, using DoesTheDogDie's authoritative per-index vote data.
- **🖥️ A real app (GUI)** — a friendly, clickable interface that runs as a **desktop window** *or* a **web app** (one codebase), with a guided setup screen, a searchable category-grouped topic picker, and a live preview. No config-file editing required.
- **🕐 Real timestamps & skip cues** — for [DTDD subscribers](https://www.doesthedogdie.com), each warning can show *when* a scene happens (`a dog dies (0:14:38)`) and a skip range (`0:14:38 → 0:16:21`), pulled from DTDD's timeline.
- **🗂️ Category grouping** — warnings can be grouped under their DTDD category with per-category emoji, instead of one long line.
- **💬 Scene descriptions you choose** — a **review-before-commit** workflow where each trigger's descriptions (timestamped timeline scenes *and* community comments) can be picked per-scene, per item, and land under the right category.
- **⚙️ Layered, GUI-editable config** — settings resolve `env var → settings.json → config.py`, shared by the GUI, CLI, and Docker so they never drift.
- **🐳 Container-ready** — a web-GUI Docker image (`Dockerfile.gui`) plus a CI build, for running it as a stack service behind your own SSO.

<details>
<summary><b>How it works (in brief)</b></summary>

- **Matching:** IMDb id first (via Plex GUID metadata), then title+year. TV shows match once at the series level to resolve a DTDD id, then use indexed lookups for seasons/episodes.
- **Filtering:** warnings are gated by community vote count + confidence ratio, so you only see things the community is reasonably sure about.
- **Idempotent & reversible:** safe to re-run (existing blocks are replaced); `--clear` removes everything it added, restoring the original summaries.

</details>

## ⚠️ A note on episode/season accuracy

DTDD's per-index data is community-sourced and uneven. A chunk of **series-wide** votes get attributed to the **first season and first episode** (DTDD's default bucket for votes cast without a specific index), so *Season 1* and *S1E1* tend to over-report — they inherit warnings that really apply to the whole show — while later seasons/episodes are clean. (Game of Thrones Season 1 returns ~13 topics vs ~1 for Seasons 2–6.) The **series level is the most complete**; treat S1/S1E1 as approximate. This is a DTDD data quirk, not a matching bug. See the [Roadmap](#-roadmap) for the planned mitigation.

## 🗺️ Roadmap

- ✅ **GUI for settings & topic selection** — desktop window + web app.
- ✅ **Timestamps / skip cues** for DTDD subscribers.
- **Packaged installers** — pre-built `.exe` / `.dmg` / `.AppImage` (via `flet build`) so non-technical users can download and double-click, no Python.
- **Smarter S1 / S1E1 attribution** — cross-reference later episodes to detect series-wide topics wrongly dumped on episode 1.
- **Per-library configuration** — different thresholds or topic filters per Plex library.

## 🙏 Credits

- Original concept: [valknight/DoesTheDogWatchPlex](https://github.com/valknight/DoesTheDogWatchPlex) (2018).
- Modern rebuild this fork is based on: [justkorix/DoesTheDogWatchPlex](https://github.com/justkorix/DoesTheDogWatchPlex).
- TV-show work drew on community efforts toward the same goal, including [greghesp's `feature/tv-show-support`](https://github.com/greghesp/DoesTheDogWatchPlex/tree/feature/tv-show-support) branch.
- All the content-warning data: the [DoesTheDogDie.com](https://www.doesthedogdie.com) community.

> 🤖 Built with the help of [Claude Code](https://claude.com/claude-code) (Anthropic Claude Opus 4.8). The TV engine, the GUI, the timecode scraping, and the Docker/CI setup were developed in collaboration with Claude.

## 📄 License

MIT — see [LICENSE](LICENSE). This is a derivative work; the upstream project is MIT-licensed and that notice is retained.
