#!/usr/bin/env python3
"""
DoesTheDogWatchPlex — desktop & web GUI (Flet).

Run it as a friendly desktop window (no port to manage):

    python gui.py

Or serve it for a stack / Docker deployment:

    python gui.py --web            # binds DTDD_GUI_PORT (default 8550)

Both modes are the same code. Settings the user changes are saved to settings.json
via the shared `settings` module; the actual work is done by the same engine the
CLI uses (`plex_warnings`), so the GUI and command line never diverge.
"""
from __future__ import annotations

import contextlib
import io
import os
import sys
import threading

import flet as ft

import settings
import plex_warnings as engine


# --- Vaporwave / cyberpunk / retrofuturist palette --------------------------
BG          = "#0d0221"   # deep space indigo
PANEL       = "#190b33"   # raised panel
PANEL_EDGE  = "#2a1a4a"
NEON_PINK   = "#ff2e97"
NEON_CYAN   = "#00e5ff"
NEON_PURPLE = "#b76cff"
NEON_AMBER  = "#ffcc55"
TEXT        = "#e8e0ff"
TEXT_DIM    = "#9a86c4"
OK_GREEN    = "#46f4a0"
MONO        = "JetBrains Mono, Consolas, monospace"

# Small fake DTDD payload so the Appearance preview matches real engine output.
SAMPLE_MEDIA = {"topicItemStats": [
    {"yesSum": 50, "noSum": 1, "topic": {"name": "a dog dies", "notName": "no dogs die",
        "TopicCategory": {"name": "Animal Death"}}},
    {"yesSum": 44, "noSum": 2, "topic": {"name": "an animal is sad", "notName": "no animal is sad",
        "TopicCategory": {"name": "Animal Distress"}}},
    {"yesSum": 41, "noSum": 1, "topic": {"name": "someone is assaulted", "notName": "no one is assaulted",
        "TopicCategory": {"name": "Violence"}}},
    {"yesSum": 33, "noSum": 1, "topic": {"name": "the ending is sad", "notName": "the ending is happy",
        "TopicCategory": {"name": "Loss"}}},
]}

QUICK_EMOJI = ["⚠️", "🚨", "❗", "⛔", "🔞", "📛", "💀", "🩸", "🔪", "🐾"]

# Settings categories shown in the left rail (only on the Run tab).
GROUPS = ["Connection", "Libraries", "Filtering", "Topics", "Appearance", "Advanced"]
GROUP_ICONS = {
    "Connection": ft.Icons.POWER,
    "Libraries":  ft.Icons.VIDEO_LIBRARY,
    "Filtering":  ft.Icons.FILTER_ALT,
    "Topics":     ft.Icons.CHECKLIST,
    "Appearance": ft.Icons.PALETTE,
    "Advanced":   ft.Icons.TUNE,
}

MAX_REVIEW_TABS = 5      # how many review tabs can be open at once

# Short, friendly "how do I get this?" explainers for the setup screen.
EXPLAINERS = {
    "DTDD_API_KEY": (
        "Free. Make an account at doesthedogdie.com, open your Profile page, "
        "and copy the API key shown there.",
        "https://www.doesthedogdie.com/signup",
        "Open doesthedogdie.com",
    ),
    "PLEX_TOKEN": (
        "In Plex web, play any title, click ⋮ → Get Info → View XML, and copy the "
        "X-Plex-Token value from the address bar.",
        "https://support.plex.tv/articles/204059436-finding-an-authentication-token-x-plex-token/",
        "Plex token guide",
    ),
}


def _spec(key):
    return next(s for s in settings.SCHEMA if s["key"] == key)


class DTDDApp:
    def __init__(self, page: ft.Page):
        self.page = page
        self.controls: dict = {}          # schema key -> {"get": callable, "set": callable}
        self.topic_catalog: list[str] = []
        self.topic_desc: dict[str, str] = {}      # name -> tooltip text
        self.topic_cat: dict[str, str] = {}       # name -> category
        self.include_set: set[str] = set(settings.get("INCLUDE_TOPICS") or [])
        self.exclude_set: set[str] = set(settings.get("EXCLUDE_TOPICS") or [])
        self.topic_mode = "include"       # which list the topic checkboxes edit
        self._topic_shown = 0
        self._topic_ncats = 0
        self.open_tabs: list[dict] = []   # document tabs: Run + review tabs
        self.active_tab = "run"
        self._review_seq = 0              # uniquifies review tab ids
        self.busy = False
        self.cancel_requested = False     # cooperative cancel flag for running jobs
        self._build()

    # -- value collection ----------------------------------------------------
    def collect(self) -> dict:
        values = {}
        for key, io_ in self.controls.items():
            values[key] = io_["get"]()
        values["INCLUDE_TOPICS"] = sorted(self.include_set) or None
        values["EXCLUDE_TOPICS"] = sorted(self.exclude_set) or None
        return values

    def stage(self):
        """Push current field values into the engine (memory only)."""
        settings.stage(self.collect())

    # -- field factory -------------------------------------------------------
    def _field(self, key) -> ft.Control:
        spec = _spec(key)
        t = spec["type"]
        cur = settings.get(key)

        if t in ("str", "text", "password"):
            tf = ft.TextField(
                label=spec["label"], value="" if cur is None else str(cur),
                password=(t == "password"), can_reveal_password=(t == "password"),
                multiline=(t == "text"), min_lines=1, max_lines=3 if t == "text" else 1,
                hint_text=spec.get("help"), border_color=PANEL_EDGE, color=TEXT,
                cursor_color=NEON_CYAN, focused_border_color=NEON_CYAN,
                label_style=ft.TextStyle(color=TEXT_DIM),
                text_size=13,
            )
            self.controls[key] = {"get": lambda tf=tf: tf.value or None,
                                  "set": lambda v, tf=tf: setattr(tf, "value", "" if v is None else str(v)),
                                  "ctl": tf}
            return tf

        if t in ("int", "float"):
            tf = ft.TextField(
                label=spec["label"], value="" if cur is None else str(cur),
                width=200, border_color=PANEL_EDGE, color=TEXT,
                cursor_color=NEON_CYAN, focused_border_color=NEON_CYAN,
                label_style=ft.TextStyle(color=TEXT_DIM), text_size=13,
                keyboard_type=ft.KeyboardType.NUMBER, hint_text=spec.get("help"),
            )
            def _get(tf=tf, t=t):
                v = (tf.value or "").strip()
                if v == "":
                    return None
                try:
                    return int(v) if t == "int" else float(v)
                except ValueError:
                    return None
            self.controls[key] = {"get": _get,
                                  "set": lambda v, tf=tf: setattr(tf, "value", "" if v is None else str(v)),
                                  "ctl": tf}
            return tf

        if t == "bool":
            sw = ft.Switch(label=spec["label"], value=bool(cur),
                           active_color=NEON_PINK, label_text_style=ft.TextStyle(color=TEXT))
            self.controls[key] = {"get": lambda sw=sw: bool(sw.value),
                                  "set": lambda v, sw=sw: setattr(sw, "value", bool(v)),
                                  "ctl": sw}
            return ft.Column([sw, self._hint(spec.get("help"))], spacing=2)

        if t == "choice":
            labels = spec.get("choice_labels", {})
            rg = ft.RadioGroup(
                value=cur if cur in spec["choices"] else spec.get("default"),
                content=ft.Row([ft.Radio(value=opt, label=labels.get(opt, opt),
                                         active_color=NEON_PINK,
                                         label_style=ft.TextStyle(color=TEXT))
                                for opt in spec["choices"]], wrap=True),
            )
            self.controls[key] = {"get": lambda rg=rg: rg.value,
                                  "set": lambda v, rg=rg: setattr(rg, "value", v),
                                  "ctl": rg}
            return ft.Column([ft.Text(spec["label"], color=TEXT_DIM, size=13), rg,
                              self._hint(spec.get("help"))], spacing=4)

        if t == "multichoice":
            cur_list = cur or []
            labels = spec.get("choice_labels", {})
            pairs = []  # (canonical_value, checkbox)
            for opt in spec["choices"]:
                cb = ft.Checkbox(label=labels.get(opt, opt), value=(opt in cur_list),
                                 active_color=NEON_PINK, check_color=BG,
                                 label_style=ft.TextStyle(color=TEXT))
                pairs.append((opt, cb))
            self.controls[key] = {
                "get": lambda pairs=pairs: [opt for opt, cb in pairs if cb.value] or None,
                "set": lambda v, pairs=pairs: [setattr(cb, "value", opt in (v or [])) for opt, cb in pairs],
            }
            return ft.Column([
                ft.Text(spec["label"], color=TEXT_DIM, size=13),
                ft.Row([cb for _, cb in pairs], wrap=True),
                self._hint(spec.get("help")),
            ], spacing=4)

        if t == "list":
            txt = "" if not cur else "\n".join(cur)
            tf = ft.TextField(
                label=spec["label"], value=txt, multiline=True, min_lines=2, max_lines=6,
                hint_text=(spec.get("help") or "") + "  (one per line; empty = all)",
                border_color=PANEL_EDGE, color=TEXT, cursor_color=NEON_CYAN,
                focused_border_color=NEON_CYAN, label_style=ft.TextStyle(color=TEXT_DIM),
                text_size=13,
            )
            def _get(tf=tf):
                items = [ln.strip() for ln in (tf.value or "").splitlines() if ln.strip()]
                return items or None
            self.controls[key] = {"get": _get,
                                  "set": lambda v, tf=tf: setattr(tf, "value", "\n".join(v or [])),
                                  "ctl": tf}
            return tf

        # fallback
        tf = ft.TextField(label=spec["label"], value="" if cur is None else str(cur),
                          border_color=PANEL_EDGE, color=TEXT)
        self.controls[key] = {"get": lambda tf=tf: tf.value or None,
                              "set": lambda v, tf=tf: setattr(tf, "value", "" if v is None else str(v))}
        return tf

    def _hint(self, text):
        return ft.Text(text or "", color=TEXT_DIM, size=11, italic=True)

    def _explainer(self, key) -> ft.Control:
        """The 'how do I get this?' helper card for setup fields."""
        info = EXPLAINERS.get(key)
        if not info:
            return ft.Container()
        msg, url, link_label = info
        return ft.Container(
            content=ft.Row([
                ft.Icon(ft.Icons.HELP_OUTLINE, color=NEON_CYAN, size=16),
                ft.Column([
                    ft.Text(msg, color=TEXT_DIM, size=12, selectable=True),
                    ft.TextButton(content=ft.Text(link_label + " ↗", color=NEON_CYAN, size=12),
                                  url=url),
                ], spacing=2, expand=True),
            ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.START),
            bgcolor="#120826", border=ft.Border.all(1, PANEL_EDGE),
            border_radius=8, padding=10,
        )

    # -- tab builders --------------------------------------------------------
    def _group_fields(self, group) -> list[ft.Control]:
        out = []
        for spec in settings.SCHEMA:
            if spec["group"] != group:
                continue
            out.append(self._field(spec["key"]))
            if spec["key"] in EXPLAINERS:
                out.append(self._explainer(spec["key"]))
            out.append(ft.Container(height=6))
        return out

    def _connection_tab(self):
        header = ft.Column([
            ft.Text("Setup", size=22, weight=ft.FontWeight.BOLD, color=NEON_PINK, font_family=MONO),
            ft.Text("Point this at your Plex server and paste your DoesTheDogDie key. "
                    "The two help cards below tell you exactly where to find each one.",
                    color=TEXT_DIM, size=13),
            ft.Container(height=8),
        ], spacing=4)
        return ft.Column([header, *self._group_fields("Connection")],
                         scroll=ft.ScrollMode.AUTO, expand=True)

    def _topics_tab(self):
        self.topic_search = ft.TextField(
            hint_text="search topics…", border_color=PANEL_EDGE, color=TEXT,
            cursor_color=NEON_CYAN, focused_border_color=NEON_CYAN, text_size=13,
            prefix_icon=ft.Icons.SEARCH, on_change=lambda e: self._render_topics(),
            expand=True,
        )
        self.topic_list = ft.ListView(expand=True, spacing=1, padding=4)
        self.topic_count = ft.Text("", color=TEXT_DIM, size=12)
        self.mode_toggle = ft.RadioGroup(
            value=self.topic_mode, on_change=self._switch_mode,
            content=ft.Row([
                ft.Radio(value="include", label="Only these (include)",
                         active_color=NEON_PINK, label_style=ft.TextStyle(color=TEXT)),
                ft.Radio(value="exclude", label="Hide these (exclude)",
                         active_color=NEON_CYAN, label_style=ft.TextStyle(color=TEXT)),
            ], wrap=True),
        )
        load_btn = ft.Button(content="Load topics from DTDD", icon=ft.Icons.CLOUD_DOWNLOAD,
                             bgcolor=PANEL, color=NEON_CYAN, on_click=lambda e: self._load_topics())
        return ft.Column([
            ft.Text("Topics", size=22, weight=ft.FontWeight.BOLD, color=NEON_PINK, font_family=MONO),
            ft.Text("Pick which content topics to show. 'Include' means ONLY those appear; "
                    "'Exclude' hides them. Load the list once, then tick what you want.",
                    color=TEXT_DIM, size=13),
            ft.Row([self.mode_toggle, load_btn], alignment=ft.MainAxisAlignment.SPACE_BETWEEN, wrap=True),
            self.topic_count,
            ft.Container(content=self.topic_list, expand=True, bgcolor=PANEL,
                         border=ft.Border.all(1, PANEL_EDGE), border_radius=8),
            ft.Row([self.topic_search]),
        ], expand=True, spacing=8)

    def _appearance_tab(self):
        fields = self._group_fields("Appearance")
        # live preview
        self.preview = ft.Text("", color=TEXT, size=13, selectable=True, font_family=MONO)
        # refresh the preview whenever any appearance field changes
        for key in ("WARNING_LAYOUT", "USE_CATEGORY_ICONS", "SEPARATOR",
                    "WARN_PREFIX", "SAFE_PREFIX", "TOPIC_DELIMITER"):
            ctl = self.controls.get(key, {}).get("ctl")
            if ctl is not None:
                ctl.on_change = lambda e: self._refresh_preview()
        # quick-pick emoji row for the warning prefix
        emoji_row = ft.Row([
            ft.Text("Quick icons:", color=TEXT_DIM, size=12),
            *[ft.Button(content=ft.Text(em, size=16), bgcolor=PANEL,
                        on_click=lambda e, em=em: self._set_prefix(em))
              for em in QUICK_EMOJI],
        ], wrap=True, spacing=4)
        preview_card = ft.Container(
            content=ft.Column([
                ft.Text("PREVIEW — how it appears in a Plex summary", color=NEON_CYAN,
                        size=11, weight=ft.FontWeight.BOLD),
                ft.Divider(color=PANEL_EDGE, height=8),
                ft.Text("Your original summary text…", color=TEXT_DIM, size=13, italic=True),
                self.preview,
            ], spacing=4),
            bgcolor=PANEL, border=ft.Border.all(1, NEON_PURPLE), border_radius=8, padding=14,
        )
        self._refresh_preview()
        return ft.Column([
            ft.Text("Appearance", size=22, weight=ft.FontWeight.BOLD, color=NEON_PINK, font_family=MONO),
            ft.Text("Customize how the warning block looks inside Plex.", color=TEXT_DIM, size=13),
            ft.Container(height=4), *fields, ft.Container(height=6), emoji_row,
            ft.Container(height=8), preview_card,
        ], scroll=ft.ScrollMode.AUTO, expand=True)

    def _set_prefix(self, emoji):
        ctl = self.controls.get("WARN_PREFIX", {}).get("ctl")
        if ctl is not None:
            ctl.value = emoji + "  "
            self._refresh_preview()

    def _dry_run(self, force_all=False):
        """Bottom-bar 'Dry run': open a new Review tab with the matching warnings."""
        review_tabs = [t for t in self.open_tabs if t["id"] != "run"]
        if len(review_tabs) >= MAX_REVIEW_TABS:
            oldest = review_tabs[0]["id"]
            self.open_tabs = [t for t in self.open_tabs if t["id"] != oldest]
            self._log(f"Review tab limit ({MAX_REVIEW_TABS}) reached — closed the oldest.")

        target = "" if force_all else (self.show_field.value or "").strip()
        self._review_seq += 1
        tab_id = f"review{self._review_seq}"
        title = f"Review: {target}" if target else "Review: ALL"

        # per-tab state + UI
        review_list = ft.ListView(expand=True, spacing=8, padding=4,
                                  controls=[ft.Text("Building…", color=TEXT_DIM, size=12)])
        state = {"id": tab_id, "items": [], "list": review_list}
        commit_btn = ft.Button(content="Commit this review → Plex", icon=ft.Icons.CLOUD_UPLOAD,
                               bgcolor=NEON_PINK, color=BG,
                               tooltip="Write everything in THIS review tab to Plex",
                               on_click=lambda e, st=state: self._commit(st))
        content = ft.Column([
            ft.Row([ft.Text(title, size=18, weight=ft.FontWeight.BOLD, color=NEON_PINK, font_family=MONO),
                    commit_btn], alignment=ft.MainAxisAlignment.SPACE_BETWEEN, wrap=True),
            ft.Text("Tick a trigger to also write its scene description (off by default), then Commit.",
                    color=TEXT_DIM, size=12),
            ft.Container(content=review_list, expand=True, bgcolor="#0a0118",
                         border=ft.Border.all(1, PANEL_EDGE), border_radius=8, padding=6),
        ], expand=True, spacing=8)
        content = ft.Container(content=content, expand=True, padding=16)

        self.open_tabs.append({"id": tab_id, "title": title, "content": content, "closeable": True})
        self.active_tab = tab_id
        self._render_tabs()
        self._build_review(state, target)

    def _build_review(self, state, target):
        def task():
            self.stage()
            state["items"] = []
            state["list"].controls = []
            self.page.update()
            try:
                plex = engine.connect_plex()
            except Exception as ex:
                self._log(f"✗ Plex connection failed: {ex}")
                return
            dtdd = engine.make_client()
            levels = settings.get("TV_WARNING_LEVELS")
            names = settings.get("PLEX_LIBRARIES")
            count = 0

            def add_show(show):
                nonlocal count
                for item, label, media, i1, i2 in engine.iter_show_media(dtdd, show, levels):
                    if self.cancel_requested:
                        return
                    if self._add_review_card(state, item, label, media,
                                             engine.build_item_timeline(dtdd, media)):
                        count += 1

            def add_movie(m):
                nonlocal count
                media = engine.match_movie(dtdd, m)
                if media and self._add_review_card(
                        state, m, f"{m.title} ({m.year})" if m.year else m.title,
                        media, engine.build_item_timeline(dtdd, media)):
                    count += 1

            stopped = False
            for lib in engine.get_libraries(plex, names, settings.get("PLEX_LIBRARY_TYPES")):
                items = lib.search(title=target) if target else lib.all()
                for it in items:
                    if self.cancel_requested:
                        stopped = True
                        break
                    if lib.type == "show":
                        add_show(it)
                    else:
                        add_movie(it)
                if stopped:
                    break

            if not state["items"]:
                state["list"].controls = [ft.Text("No items with warnings found for this scope.",
                                                  color=TEXT_DIM, size=12)]
                self.page.update()
            self._log(f"Dry run {'stopped' if stopped else 'complete'}: {count} item(s) in this "
                      f"Review tab. Tick descriptions, then ‘Commit this review → Plex’.")
        self._run_bg(task, "Dry run → building review…")

    def _write_now(self):
        """Bottom-bar 'Write now': process the scope and write straight to Plex."""
        target = (self.show_field.value or "").strip()

        def task():
            self.stage()
            try:
                plex = engine.connect_plex()
            except Exception as ex:
                self._log(f"✗ Plex connection failed: {ex}")
                return
            dtdd = engine.make_client()
            levels = settings.get("TV_WARNING_LEVELS")
            names = settings.get("PLEX_LIBRARIES")
            stopped = False
            with self._capture():
                for lib in engine.get_libraries(plex, names, settings.get("PLEX_LIBRARY_TYPES")):
                    items = lib.search(title=target) if target else lib.all()
                    if not target:
                        print(f"\nProcessing: {lib.title} ({len(items)} items)")
                    for it in items:
                        if self.cancel_requested:
                            stopped = True
                            break
                        if lib.type == "show":
                            engine.process_show(dtdd, it, dry_run=False, levels=levels)
                        else:
                            engine.process_movie(dtdd, it, dry_run=False)
                    if stopped:
                        break
            self._log("Write now stopped." if stopped else "Write now complete.")
        self._run_bg(task, "Write now → writing to Plex…")

    def _add_review_card(self, state, item, label, media, timeline) -> bool:
        base = engine.format_warnings(media, timeline=timeline)
        if not base:
            return False
        # selected = {topic_lower: [chosen description lines]} so the engine can place
        # them under their category (categorized layout) rather than at the bottom.
        rec = {"item": item, "label": label, "media": media, "timeline": timeline, "selected": {}}
        preview = ft.Text(base, color=TEXT, size=12, font_family=MONO, selectable=True)
        rec["preview"] = preview

        # Per-trigger description options from BOTH sources: timeline scenes (with a
        # timestamp) and community comments (no timestamp). Each is a checkbox; ticking
        # adds its "↳ topic[ (time)]: description" line to what gets written.
        yes, _ = engine._evaluate_warnings(media)
        sections = []
        for w in yes:
            options = []  # (checkbox_label, line_to_write)
            # timeline scenes (timestamped)
            for e in (timeline.get(w["name"].lower()) if timeline else []) or []:
                desc = (e.get("description") or "").strip()
                if not desc:
                    continue
                start = e.get("start")
                options.append(((f"[{start}] " if start else "") + desc,
                                f"   ↳ {w['name']}{(' (' + start + ')') if start else ''}: {desc}"))
            # community comments (no timestamp), best-voted first
            comments = sorted([c for c in (w["stat"].get("comments") or [])
                               if (c.get("comment") or "").strip()],
                              key=lambda c: -c.get("voteSum", 0))
            for c in comments[:5]:
                cm = c["comment"].strip()
                votes = c.get("voteSum", 0)
                options.append((f"💬 {cm}  ({votes}▲)", f"   ↳ {w['name']}: {cm}"))
            if not options:
                continue
            key = w["name"].lower()
            boxes = [ft.Checkbox(
                label=lbl, value=False, active_color=NEON_PINK, check_color=BG,
                label_style=ft.TextStyle(color=TEXT, size=11),
                on_change=lambda e, rec=rec, k=key, ln=ln: self._toggle_desc_line(rec, k, ln, e.control.value))
                for lbl, ln in options]
            n = len(options)
            sections.append(ft.ExpansionTile(
                title=ft.Text(f"{w['name']}  ({n} description{'s' if n > 1 else ''})",
                              color=NEON_CYAN, size=12),
                controls=[ft.Container(content=ft.Column(boxes, spacing=0),
                                       padding=ft.Padding(left=16, top=0, right=0, bottom=4))],
                text_color=NEON_CYAN, collapsed_text_color=TEXT, icon_color=NEON_PINK,
                collapsed_icon_color=TEXT_DIM, dense=True, maintain_state=True))

        body = [
            ft.Text(label, color=NEON_PINK, size=13, weight=ft.FontWeight.BOLD),
            preview,
        ]
        if sections:
            body.append(ft.Text(f"▼ Optional descriptions — click a trigger to pick "
                                f"(timestamped scenes 🕐 and/or community notes 💬 · "
                                f"{len(sections)} trigger(s) have them · none added by default):",
                                color=NEON_PURPLE, size=11, weight=ft.FontWeight.BOLD))
            body.extend(sections)
        else:
            body.append(ft.Text("ℹ No scene descriptions or community notes on DoesTheDogDie "
                                "for these triggers (the warnings above are the full result).",
                                color=TEXT_DIM, size=10, italic=True))
        card = ft.Container(content=ft.Column(body, spacing=4), bgcolor=PANEL,
                            border=ft.Border.all(1, PANEL_EDGE), border_radius=8, padding=12)
        state["items"].append(rec)
        state["list"].controls.append(card)
        self.page.update()
        return True

    def _rendered_text(self, rec):
        return engine.format_warnings(rec["media"], timeline=rec["timeline"],
                                      descriptions=rec["selected"]) or ""

    def _toggle_desc_line(self, rec, key, line, on):
        lines = rec["selected"].setdefault(key, [])
        if on:
            if line not in lines:
                lines.append(line)
        else:
            rec["selected"][key] = [l for l in lines if l != line]
            if not rec["selected"][key]:
                del rec["selected"][key]
        rec["preview"].value = self._rendered_text(rec)
        self.page.update()

    def _commit(self, state):
        if not state["items"]:
            self._log("This review tab is empty — nothing to commit.")
            return

        def task():
            n = 0
            stopped = False
            with self._capture():
                for rec in state["items"]:
                    if self.cancel_requested:
                        stopped = True
                        break
                    try:
                        original = getattr(rec["item"], "summary", "") or ""
                        new_summary = (engine.strip_warnings(original) + engine.get_separator()
                                       + "\n" + self._rendered_text(rec))
                        rec["item"].editSummary(new_summary)
                        print(f"  ✓ {rec['label']}")
                        n += 1
                    except Exception as ex:
                        print(f"  ✗ {rec['label']}: {ex}")
            self._log(f"Committed {n} item(s) from this review tab to Plex"
                      f"{' (stopped early)' if stopped else ''}.")
        self._run_bg(task, "Commit → writing to Plex…")

    def _generic_tab(self, group, subtitle):
        return ft.Column([
            ft.Text(group, size=22, weight=ft.FontWeight.BOLD, color=NEON_PINK, font_family=MONO),
            ft.Text(subtitle, color=TEXT_DIM, size=13),
            ft.Container(height=4), *self._group_fields(group),
        ], scroll=ft.ScrollMode.AUTO, expand=True)

    # -- topics behavior -----------------------------------------------------
    def _active_set(self):
        return self.include_set if self.topic_mode == "include" else self.exclude_set

    def _switch_mode(self, e):
        self.topic_mode = e.control.value or "include"
        self._render_topics()

    def _cat_title(self, cat, names, active):
        icon = engine.CATEGORY_ICONS.get(cat, engine.FALLBACK_CATEGORY_ICON)
        picked = sum(1 for n in names if n in active)
        return f"{icon}  {cat}  ({picked}/{len(names)})" if picked else f"{icon}  {cat}  ({len(names)})"

    def _topic_count_text(self):
        return (f"{len(self._active_set())} selected · {self._topic_shown} of "
                f"{len(self.topic_catalog)} topics in {self._topic_ncats} categories "
                f"({self.topic_mode})")

    def _render_topics(self):
        q = (self.topic_search.value or "").strip().lower()
        active = self._active_set()

        # group matching topics by category
        by_cat: dict[str, list[str]] = {}
        shown = 0
        for name in self.topic_catalog:
            if q and q not in name.lower():
                continue
            shown += 1
            by_cat.setdefault(self.topic_cat.get(name, "Other"), []).append(name)
        self._topic_shown = shown
        self._topic_ncats = len(by_cat)

        sections = []
        for cat in sorted(by_cat):
            names = by_cat[cat]
            title_txt = ft.Text(self._cat_title(cat, names, active), color=NEON_CYAN, size=13)
            boxes = [ft.Checkbox(
                label=n, value=(n in active), active_color=NEON_PINK, check_color=BG,
                label_style=ft.TextStyle(color=TEXT, size=12),
                tooltip=self.topic_desc.get(n) or None,
                on_change=lambda e, n=n, tt=title_txt, c=cat, nm=names:
                    self._toggle_topic(n, e.control.value, tt, c, nm),
            ) for n in names]
            sections.append(ft.ExpansionTile(
                title=title_txt,
                controls=[ft.Container(content=ft.Column(boxes, spacing=0), padding=ft.Padding(left=16, top=0, right=0, bottom=4))],
                text_color=NEON_CYAN, collapsed_text_color=TEXT,
                icon_color=NEON_PINK, collapsed_icon_color=TEXT_DIM,
                expanded=bool(q),          # auto-expand when searching
                maintain_state=True, dense=True,
            ))

        self.topic_list.controls = sections
        if not self.topic_catalog:
            self.topic_count.value = "No topics loaded yet — click ‘Load topics from DTDD’."
        else:
            self.topic_count.value = self._topic_count_text()
        self.page.update()

    def _toggle_topic(self, name, on, title_txt, cat, names):
        # Update only this category's count + the totals — no full re-render, so the
        # category stays open and the scroll position holds while you tick boxes.
        s = self._active_set()
        if on:
            s.add(name)
        else:
            s.discard(name)
        title_txt.value = self._cat_title(cat, names, s)
        self.topic_count.value = self._topic_count_text()
        self.page.update()

    def _load_topics(self):
        def task():
            self.stage()
            try:
                topics = engine.fetch_topics(engine.make_client())
                self.topic_catalog = [t["name"] for t in topics]
                self.topic_desc = {
                    t["name"]: (t["description"]
                                or (f"Keywords: {t['keywords']}" if t["keywords"] else ""))
                    for t in topics
                }
                self.topic_cat = {t["name"]: t["category"] for t in topics}
                ncats = len(set(self.topic_cat.values()))
                self._log(f"Loaded {len(self.topic_catalog)} topics in {ncats} categories. "
                          f"Hover a topic for its description.")
            except Exception as ex:
                self._log(f"✗ Could not load topics: {ex}")
            self._render_topics()
        self._run_bg(task, "Loading topics…")

    # -- appearance preview --------------------------------------------------
    def _refresh_preview(self):
        # Stage current appearance values (ignoring topic filters so the sample
        # always shows) and render through the real engine for an exact preview.
        vals = self.collect()
        vals["INCLUDE_TOPICS"] = None
        vals["EXCLUDE_TOPICS"] = None
        vals["SHOW_SAFE_TOPICS"] = False
        settings.stage(vals)
        try:
            block = engine.format_warnings(SAMPLE_MEDIA) or "(nothing would show)"
        except Exception as ex:
            block = f"(preview error: {ex})"
        finally:
            settings.reload()
        sep = (vals.get("SEPARATOR") or "").strip("\n")
        self.preview.value = f"{sep}\n{block}"
        self.page.update()

    # -- engine actions ------------------------------------------------------
    def _save(self, e=None):
        settings.save(self.collect())
        self._log("✓ Settings saved to settings.json")

    def _clear_cache(self, e=None):
        def task():
            self.stage()
            engine.make_client().clear_cache()
            self._log("✓ Cache cleared — next run fetches fresh data (incl. subscriber timecodes).")
        self._run_bg(task, "Clearing cache…")

    def _test(self, e=None):
        def task():
            self.stage()
            if not settings.get("DTDD_API_KEY"):
                self._log("✗ No DoesTheDogDie API key entered.")
                return
            try:
                res = engine.make_client().search("Avengers Endgame")
                self._log(f"✓ DoesTheDogDie key works ({len(res)} results for a test search).")
            except Exception as ex:
                self._log(f"✗ DTDD key/connection failed: {ex}")
            try:
                plex = engine.connect_plex()
                self._log(f"✓ Connected to Plex: {plex.friendlyName}")
            except Exception as ex:
                self._log(f"✗ Plex connection failed: {ex}")
        self._run_bg(task, "Testing connection…")

    def _clear(self, e=None):
        def do_clear():
            self.page.pop_dialog()
            def task():
                self.stage()
                try:
                    plex = engine.connect_plex()
                except Exception as ex:
                    self._log(f"✗ Plex connection failed: {ex}")
                    return
                with self._capture():
                    engine.clear_warnings(plex, settings.get("PLEX_LIBRARIES"),
                                          settings.get("PLEX_LIBRARY_TYPES"))
                self._log("— cleared —")
            self._run_bg(task, "Clearing warnings…")
        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Text("Remove all content warnings?", color=TEXT),
            content=ft.Text("This strips DoesTheDogDie blocks from every movie/series/season/"
                            "episode summary in the selected libraries. Original summaries are kept.",
                            color=TEXT_DIM),
            actions=[
                ft.TextButton(content=ft.Text("Cancel", color=TEXT_DIM),
                              on_click=lambda e: self.page.pop_dialog()),
                ft.Button(content="Remove warnings", bgcolor=NEON_PINK, color=BG,
                          on_click=lambda e: do_clear()),
            ],
            bgcolor=PANEL,
        )
        self.page.show_dialog(dlg)

    # -- background execution + log -----------------------------------------
    @contextlib.contextmanager
    def _capture(self):
        """Redirect engine print() output into the on-screen log."""
        class _W(io.TextIOBase):
            def write(_self, s):
                if s.strip():
                    self._log(s.rstrip("\n"))
                return len(s)
        with contextlib.redirect_stdout(_W()):
            yield

    def _run_bg(self, task, status):
        if self.busy:
            self._log("· busy — wait for the current job to finish, or click Stop.")
            return
        self.busy = True
        self.cancel_requested = False
        self.spinner.visible = True
        self.stop_btn.visible = True
        self.status.value = status
        self.page.update()

        def runner():
            try:
                task()
            except Exception as ex:
                self._log(f"✗ Error: {ex}")
            finally:
                self.busy = False
                self.cancel_requested = False
                self.spinner.visible = False
                self.stop_btn.visible = False
                self.status.value = "Ready"
                self.page.update()
        self.page.run_thread(runner)

    def _stop(self, e=None):
        if self.busy:
            self.cancel_requested = True
            self.status.value = "Stopping…"
            self._log("⛔ Stop requested — halting after the current item.")
            self.page.update()

    def _log(self, line):
        self.log.controls.append(ft.Text(line, color=TEXT, size=12, font_family=MONO, selectable=True))
        self.log.controls[:] = self.log.controls[-400:]
        self.page.update()

    # -- assemble ------------------------------------------------------------
    def _build(self):
        page = self.page
        page.title = "DoesTheDogWatchPlex"
        page.theme_mode = ft.ThemeMode.DARK
        page.bgcolor = BG
        page.padding = 0
        page.fonts = {"JetBrains Mono": "https://github.com/JetBrains/JetBrainsMono/raw/master/fonts/webfonts/JetBrainsMono-Regular.woff2"}

        # settings categories (left rail content on the Run tab; Review is NOT here)
        self.tabs = {
            "Connection": self._connection_tab(),
            "Libraries":  self._generic_tab("Libraries", "Which Plex libraries to process, and which TV levels to write."),
            "Filtering":  self._generic_tab("Filtering", "Confidence thresholds and optional translation."),
            "Topics":     self._topics_tab(),
            "Appearance": self._appearance_tab(),
            "Advanced":   self._generic_tab("Advanced", "Rate limiting, caching, and dry-run default."),
        }
        self.body = ft.Container(content=self.tabs["Connection"], expand=True, padding=20)
        self.rail = ft.NavigationRail(
            selected_index=0, extended=True, min_extended_width=180, bgcolor=PANEL,
            destinations=[ft.NavigationRailDestination(icon=GROUP_ICONS[g], label=g) for g in GROUPS],
            on_change=self._nav,
            indicator_color=ft.Colors.with_opacity(0.25, NEON_PINK),
        )

        # run options (Run tab only)
        self.show_field = ft.TextField(
            hint_text="title — blank = ALL libraries", width=230, border_color=PANEL_EDGE,
            color=TEXT, cursor_color=NEON_CYAN, focused_border_color=NEON_CYAN,
            prefix_icon=ft.Icons.MOVIE_FILTER, text_size=13,
        )
        self.spinner = ft.ProgressRing(width=18, height=18, color=NEON_CYAN, visible=False)
        self.status = ft.Text("Ready", color=TEXT_DIM, size=12)
        self.stop_btn = ft.Button(content="Stop", icon=ft.Icons.STOP_CIRCLE, bgcolor="#4a0a1a",
                                  color=NEON_PINK, visible=False,
                                  tooltip="Cancel the running job (stops after the current item)",
                                  on_click=self._stop)
        buttons = ft.Row([
            ft.Button(content="Save", icon=ft.Icons.SAVE, bgcolor=PANEL, color=TEXT,
                      tooltip="Save your settings to settings.json", on_click=self._save),
            ft.Button(content="Test", icon=ft.Icons.WIFI_TETHERING, bgcolor=PANEL, color=NEON_CYAN,
                      tooltip="Check the Plex + DoesTheDogDie connections", on_click=self._test),
            ft.Button(content="Clear cache", icon=ft.Icons.CACHED, bgcolor=PANEL, color=TEXT_DIM,
                      tooltip="Wipe cached DTDD responses — do this after subscribing so timecodes refresh",
                      on_click=self._clear_cache),
            ft.Container(width=12),
            ft.Text("Scope:", color=TEXT_DIM, size=12), self.show_field,
            ft.Button(content="Dry run → Review", icon=ft.Icons.VISIBILITY, bgcolor=PANEL, color=NEON_AMBER,
                      tooltip="Open a Review tab with the matching warnings. Nothing is written.",
                      on_click=lambda e: self._dry_run()),
            ft.Button(content="Write now (skip review)", icon=ft.Icons.BOLT, bgcolor="#3a2a0a", color=NEON_AMBER,
                      tooltip="Match and write straight to Plex with no review step.",
                      on_click=lambda e: self._write_now()),
            ft.Container(width=12),
            ft.Button(content="Clear", icon=ft.Icons.DELETE_SWEEP, bgcolor=PANEL, color=NEON_PINK,
                      tooltip="Remove all DoesTheDogDie warnings from Plex", on_click=self._clear),
            self.stop_btn,
            self.spinner, self.status,
        ], wrap=True, spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER)
        legend = ft.Text(
            "Dry run = opens a Review tab to preview (no changes)   ·   "
            "Write now = write straight to Plex, skipping review   ·   "
            "each Review tab has its own ‘Commit → Plex’ button",
            color=TEXT_DIM, size=11)
        run_options = ft.Container(
            content=ft.Column([buttons, legend], spacing=6),
            bgcolor=PANEL, padding=12, border=ft.Border.only(top=ft.BorderSide(1, PANEL_EDGE)),
        )
        run_tab_content = ft.Column([
            ft.Row([self.rail, ft.VerticalDivider(width=1, color=PANEL_EDGE), self.body],
                   expand=True, spacing=0),
            run_options,
        ], expand=True, spacing=0)

        # document tabs (Run home + review tabs)
        self.open_tabs = [{"id": "run", "title": "⌂ Run", "content": run_tab_content, "closeable": False}]
        self.active_tab = "run"
        self.tab_bar = ft.Row([], spacing=6, scroll=ft.ScrollMode.AUTO, vertical_alignment=ft.CrossAxisAlignment.CENTER)
        tab_bar_container = ft.Container(
            content=self.tab_bar, bgcolor="#140033",
            padding=ft.Padding(left=10, right=10, top=6, bottom=6),
            border=ft.Border.only(bottom=ft.BorderSide(1, PANEL_EDGE)))
        self.doc_body = ft.Container(expand=True)

        # global log strip (always visible, all tabs)
        self.log = ft.ListView(spacing=1, padding=8, auto_scroll=True, expand=True)
        log_strip = ft.Container(
            content=ft.Column([
                ft.Text("LOG", color=NEON_CYAN, size=10, weight=ft.FontWeight.BOLD),
                ft.Container(content=self.log, expand=True),
            ], spacing=2),
            bgcolor="#0a0118", border=ft.Border.only(top=ft.BorderSide(1, PANEL_EDGE)),
            padding=8, height=130)

        header = ft.Container(
            content=ft.Text("▞▚ DOES THE DOG WATCH PLEX", size=18, weight=ft.FontWeight.BOLD,
                            color=TEXT, font_family=MONO),
            gradient=ft.LinearGradient(begin=ft.Alignment(-1, 0), end=ft.Alignment(1, 0),
                                       colors=["#2a0a4a", "#0d0221", "#08203a"]),
            padding=16, border=ft.Border.only(bottom=ft.BorderSide(2, NEON_PINK)),
        )

        page.add(ft.Column([header, tab_bar_container, self.doc_body, log_strip], expand=True, spacing=0))
        self._render_tabs()
        self._log("Welcome. Run tab → Connection: paste your DoesTheDogDie key, Test, "
                  "then ‘Dry run → Review’ opens a review tab.")

    # -- document tabs -------------------------------------------------------
    def _tab_chip(self, t):
        active = (t["id"] == self.active_tab)
        parts = [ft.Container(content=ft.Text(t["title"], color=BG if active else TEXT, size=12,
                                              weight=ft.FontWeight.BOLD if active else None),
                              on_click=lambda e, i=t["id"]: self._select_tab(i))]
        if t["closeable"]:
            parts.append(ft.IconButton(icon=ft.Icons.CLOSE, icon_size=13, icon_color=BG if active else TEXT_DIM,
                                       tooltip="Close", on_click=lambda e, i=t["id"]: self._close_tab(i)))
        return ft.Container(
            content=ft.Row(parts, spacing=2, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            bgcolor=NEON_PINK if active else PANEL, border_radius=6,
            padding=ft.Padding(left=12, right=4 if t["closeable"] else 12, top=4, bottom=4),
            on_click=lambda e, i=t["id"]: self._select_tab(i),
        )

    def _render_tabs(self):
        self.tab_bar.controls = [self._tab_chip(t) for t in self.open_tabs]
        active = next((t for t in self.open_tabs if t["id"] == self.active_tab), self.open_tabs[0])
        self.active_tab = active["id"]
        self.doc_body.content = active["content"]
        self.page.update()

    def _select_tab(self, tab_id):
        self.active_tab = tab_id
        self._render_tabs()

    def _close_tab(self, tab_id):
        self.open_tabs = [t for t in self.open_tabs if t["id"] != tab_id]
        if self.active_tab == tab_id:
            self.active_tab = "run"
        self._render_tabs()

    def _nav(self, e):
        self.body.content = self.tabs[GROUPS[e.control.selected_index]]
        if GROUPS[e.control.selected_index] == "Appearance":
            self._refresh_preview()
        if GROUPS[e.control.selected_index] == "Topics":
            self._render_topics()
        self.page.update()


def main(page: ft.Page):
    DTDDApp(page)


if __name__ == "__main__":
    if "--web" in sys.argv or os.environ.get("DTDD_GUI_WEB"):
        port = int(os.environ.get("DTDD_GUI_PORT", "8550"))
        ft.run(main, view=ft.AppView.WEB_BROWSER, host="0.0.0.0", port=port)
    else:
        ft.run(main)
