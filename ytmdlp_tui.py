#!/usr/bin/env python3
"""
ytm-dlp TUI — a terminal UI music downloader built on yt-dlp.

Features
  * Paste a URL or type a search query (uses ytsearch)
  * Pick an audio container: MP3, M4A, Opus, FLAC, WAV, OGG, or native best
  * Pick a quality: 320k / 256k / 192k / 128k / best
  * Embed metadata & thumbnail (toggle)
  * Save path is READ from ~/.config/ytmdlp-tui/config.json,
    editable in the UI, and remembered between runs
  * Live download progress in the terminal

Requirements on your machine:
  pip install yt-dlp
  ffmpeg installed and on PATH  (needed for audio conversion)

Usage:
  python3 ytmdlp_tui.py
"""

import curses
import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

CONFIG_DIR = Path.home() / ".config" / "ytmdlp-tui"
CONFIG_FILE = CONFIG_DIR / "config.json"
DEFAULT_DOWNLOAD_DIR = str(Path.home() / "Music")

# ---------------------------------------------------------------------------
# Containers / formats yt-dlp can produce (via ffmpeg post-processing)
# ---------------------------------------------------------------------------
CONTAINERS = [
    # (label, yt-dlp --audio-format, description)
    ("MP3",       "mp3",  "universal, lossy  .mp3   (libmp3lame)"),
    ("M4A / AAC", "m4a",  "Apple-friendly .m4a (aac)"),
    ("Opus",      "opus", "best bitrate .opus (YouTube native codec)"),
    ("FLAC",      "flac", "lossless .flac (big files)"),
    ("WAV",       "wav",  "uncompressed .wav"),
    ("OGG",       "ogg",  ".ogg vorbis"),
    ("Best",      "best", "keep original stream, no re-encode"),
]

QUALITIES = ["best", "320k", "256k", "192k", "128k"]

DEFAULTS = {
    "download_dir": DEFAULT_DOWNLOAD_DIR,
    "container": "MP3",
    "quality": "320k",
    "embed_metadata": True,
    "embed_thumbnail": True,
}


# ---------------------------------------------------------------------------
# Config: read path & settings from disk
# ---------------------------------------------------------------------------
def load_config() -> dict:
    cfg = dict(DEFAULTS)
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            cfg.update({k: data[k] for k in DEFAULTS if k in data})
    except (OSError, json.JSONDecodeError):
        pass  # first run — defaults are fine
    return cfg


def save_config(cfg: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)


# ---------------------------------------------------------------------------
# yt-dlp helpers
# ---------------------------------------------------------------------------
def have_binary(name: str) -> bool:
    from shutil import which
    return which(name) is not None


def build_command(url: str, cfg: dict) -> list:
    """Assemble the yt-dlp command line for a single track."""
    audio_format = {c[0]: c[1] for c in CONTAINERS}[cfg["container"]]
    cmd = [
        "yt-dlp",
        "--no-playlist",
        "-x",                       # extract audio
        "--audio-format", audio_format,
        "--newline",                # one progress line per update
        "--progress-template",
        "download:%(progress._percent_str)s",
        "-o", os.path.join(cfg["download_dir"], "%(title)s.%(ext)s"),
    ]
    if cfg["quality"] != "best" and audio_format not in ("best", "flac", "wav"):
        cmd += ["--audio-quality", cfg["quality"]]
    if cfg["embed_metadata"]:
        cmd += ["--embed-metadata"]
    if cfg["embed_thumbnail"]:
        cmd += ["--embed-thumbnail"]
    cmd.append(url)
    return cmd


def search_youtube(query: str, limit: int = 10):
    """Return [(title, uploader, duration, url)] for a search query."""
    cmd = [
        "yt-dlp", "flat-playlist", "--print",
        "%(title)s\t%(channel)s\t%(duration)s\t%(url)s",
        f"ytsearch{limit}:{query}",
    ]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    except (subprocess.TimeoutExpired, OSError):
        return None, "yt-dlp failed to run"
    if out.returncode != 0:
        return None, (out.stderr.strip().splitlines() or ["error"])[-1]
    results = []
    for line in out.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) == 4:
            title, channel, dur, url = parts
            try:
                m, s = divmod(int(float(dur or 0)), 60)
                dur = f"{m}:{s:02d}"
            except (ValueError, TypeError):
                dur = "?"
            results.append((title, channel, dur, url))
    return results, None


# ---------------------------------------------------------------------------
# Small curses widgets
# ---------------------------------------------------------------------------
def text_input(stdscr, prompt: str, initial: str = ""):
    """Modal single-line text editor. Returns None on Esc."""
    curses.curs_set(1)
    h, w = stdscr.getmaxyx()
    win = curses.newwin(3, w - 4, h // 2 - 1, 2)
    win.keypad(True)
    buf = list(initial)
    while True:
        win.erase()
        win.border()
        win.addstr(0, 2, f" {prompt} ", curses.A_BOLD)
        win.addstr(1, 2, "".join(buf)[: w - 8])
        win.refresh()
        ch = win.getch()
        if ch in (curses.KEY_ENTER, 10, 13):
            curses.curs_set(0)
            return "".join(buf).strip() or None
        if ch == 27:  # Esc
            curses.curs_set(0)
            return None
        if ch in (curses.KEY_BACKSPACE, 127, 8):
            if buf:
                buf.pop()
        elif 32 <= ch < 127:
            buf.append(chr(ch))


def pick_from_list(stdscr, title: str, items: list, footer: str = "up/down select  Enter confirm  Esc cancel"):
    """Modal list picker. Returns index or None."""
    h, w = stdscr.getmaxyx()
    n = len(items)
    if n == 0:
        return None
    sel = 0
    top = 0
    while True:
        win = curses.newwin(h - 4, w - 4, 2, 2)
        wh, ww = win.getmaxyx()
        win.keypad(True)
        win.erase()
        win.border()
        win.addstr(0, 2, f" {title} ", curses.A_BOLD)
        avail = wh - 4
        if sel < top:
            top = sel
        if sel >= top + avail:
            top = sel - avail + 1
        for i in range(top, min(n, top + avail)):
            prefix = "> " if i == sel else "  "
            attr = curses.A_REVERSE if i == sel else curses.A_NORMAL
            text = (prefix + items[i])[: ww - 4]
            try:
                win.addstr(i - top + 2, 2, text, attr)
            except curses.error:
                pass
        win.addstr(wh - 1, 2, footer[: ww - 4], curses.A_DIM)
        win.refresh()
        ch = win.getch()
        if ch in (curses.KEY_UP, ord("k")):
            sel = (sel - 1) % n
        elif ch in (curses.KEY_DOWN, ord("j")):
            sel = (sel + 1) % n
        elif ch in (curses.KEY_ENTER, 10, 13):
            return sel
        elif ch == 27:
            return None
        elif ch in (curses.KEY_PPAGE, ord("K")):
            sel = max(0, sel - avail)
        elif ch in (curses.KEY_NPAGE, ord("J")):
            sel = min(n - 1, sel + avail)


def toggle(v: bool) -> str:
    return "[x] yes" if v else "[ ] no"


# ---------------------------------------------------------------------------
# Main menu
# ---------------------------------------------------------------------------
MENU_LABELS = [
    "Search / URL", "Container", "Quality",
    "Save folder", "Embed metadata", "Embed thumbnail",
    "---", "Download", "Quit",
]


def draw_main(stdscr, cfg: dict, sel: int, url: str, status: str):
    stdscr.erase()
    h, w = stdscr.getmaxyx()
    title = "~ ytm-dlp ~ terminal music downloader"
    stdscr.addstr(0, max(0, (w - len(title)) // 2), title, curses.A_BOLD | curses.color_pair(2))
    stdscr.addstr(1, 1, "settings file: " + str(CONFIG_FILE), curses.A_DIM)

    values = {
        "Search / URL":     url or "(empty — press Enter to type)",
        "Container":        cfg["container"],
        "Quality":          cfg["quality"],
        "Save folder":      cfg["download_dir"],
        "Embed metadata":   toggle(cfg["embed_metadata"]),
        "Embed thumbnail":  toggle(cfg["embed_thumbnail"]),
        "---":              "",
        "Download":         "start downloading the track above",
        "Quit":             "",
    }
    for i, label in enumerate(MENU_LABELS):
        attr = curses.A_REVERSE if i == sel else curses.A_NORMAL
        prefix = "> " if i == sel else "  "
        row = 3 + i
        try:
            stdscr.addstr(row, 2, f"{prefix}{label:<18}", attr)
            if label in values and values[label]:
                stdscr.addstr(row, 24, values[label][: w - 26], curses.A_DIM)
        except curses.error:
            pass

    if status:
        try:
            stdscr.addstr(h - 2, 1, status[: w - 2], curses.color_pair(1))
        except curses.error:
            pass
    try:
        stdscr.addstr(h - 1, 1, "up/down move  Enter select  q quit", curses.A_DIM)
    except curses.error:
        pass
    stdscr.refresh()


def run_download(stdscr, url: str, cfg: dict) -> str:
    """Run yt-dlp and stream its progress into the TUI. Returns a status msg."""
    try:
        os.makedirs(cfg["download_dir"], exist_ok=True)
    except OSError as e:
        return f"cannot create save folder: {e}"
    cmd = build_command(url, cfg)

    h, w = stdscr.getmaxyx()
    stdscr.erase()
    stdscr.addstr(0, 2, "Downloading...", curses.A_BOLD | curses.color_pair(2))
    try:
        stdscr.addstr(1, 2, shlex.join(cmd)[: w - 3], curses.A_DIM)
    except curses.error:
        pass
    stdscr.addstr(h - 1, 1, "press q to abort", curses.A_DIM)

    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, bufsize=1)
    pct_re = re.compile(r"([0-9.]+)%")
    bar_w = max(10, w - 14)
    lines = []
    try:
        stdscr.timeout(50)
        for raw in proc.stdout:
            raw = raw.rstrip()
            m = pct_re.search(raw)
            if m:
                try:
                    p = min(100.0, float(m.group(1)))
                except ValueError:
                    p = 0.0
                filled = int(bar_w * p / 100)
                bar = "#" * filled + "-" * (bar_w - filled)
                try:
                    stdscr.addstr(3, 2, f"[{bar}] {p:5.1f}%", curses.A_BOLD)
                except curses.error:
                    pass
            elif raw:
                lines.append(raw)
            ch = stdscr.getch()
            if ch == ord("q"):
                proc.terminate()
                return "aborted by user"
            for i, ln in enumerate(lines[-4:]):
                try:
                    stdscr.addstr(5 + i, 2, ln[: w - 3], curses.A_DIM)
                except curses.error:
                    pass
            stdscr.refresh()
        proc.wait()
    finally:
        stdscr.timeout(-1)

    if proc.returncode == 0:
        return "DONE -> " + cfg["download_dir"]
    return "yt-dlp exited with code " + str(proc.returncode)


# ---------------------------------------------------------------------------
# App loop
# ---------------------------------------------------------------------------
def app(stdscr, cfg: dict):
    curses.curs_set(0)
    curses.start_color()
    curses.use_default_colors()
    curses.init_pair(1, curses.COLOR_RED, -1)
    curses.init_pair(2, curses.COLOR_GREEN, -1)
    curses.init_pair(3, curses.COLOR_CYAN, -1)

    sel, url, status = 0, "", ""
    stdscr.keypad(True)

    while True:
        draw_main(stdscr, cfg, sel, url, status)
        ch = stdscr.getch()
        status = ""
        if ch in (curses.KEY_UP, ord("k")):
            sel = (sel - 1) % len(MENU_LABELS)
        elif ch in (curses.KEY_DOWN, ord("j")):
            sel = (sel + 1) % len(MENU_LABELS)
        elif ch == ord("q"):
            return
        elif ch in (curses.KEY_ENTER, 10, 13):
            label = MENU_LABELS[sel]
            if label == "Quit":
                return
            elif label == "Search / URL":
                got = text_input(stdscr, "Paste a URL, or type a search:", url)
                if got:
                    if not re.match(r"https?://", got):
                        results, err = search_youtube(got)
                        if err:
                            status = "search failed: " + err
                        elif results:
                            items = [f"{t[:52]:<52} {c[:16]:<16} {d:>5}" for t, c, d, _ in results]
                            idx = pick_from_list(stdscr, f"results for '{got[:30]}'", items)
                            if idx is not None:
                                url = results[idx][3]
                                status = "track selected: " + results[idx][0][:40]
                        else:
                            status = "no results"
                    else:
                        url = got
            elif label == "Container":
                idx = pick_from_list(stdscr, "audio container",
                                     [f"{name:<12} {desc}" for name, _, desc in CONTAINERS])
                if idx is not None:
                    cfg["container"] = CONTAINERS[idx][0]
            elif label == "Quality":
                idx = pick_from_list(stdscr, "audio quality (bitrate)", QUALITIES)
                if idx is not None:
                    cfg["quality"] = QUALITIES[idx]
            elif label == "Save folder":
                got = text_input(stdscr, "folder to save songs in:", cfg["download_dir"])
                if got:
                    cfg["download_dir"] = os.path.expanduser(got)
                    status = "save folder updated"
            elif label == "Embed metadata":
                cfg["embed_metadata"] = not cfg["embed_metadata"]
            elif label == "Embed thumbnail":
                cfg["embed_thumbnail"] = not cfg["embed_thumbnail"]
            elif label == "Download":
                if not url:
                    status = "enter a search or URL first"
                elif not have_binary("yt-dlp"):
                    status = "yt-dlp not found - pip install yt-dlp"
                elif not have_binary("ffmpeg"):
                    status = "ffmpeg not found - install it to convert audio"
                else:
                    status = run_download(stdscr, url, cfg)
            save_config(cfg)


def main():
    if not sys.stdin.isatty():
        print("this is a TUI - run it in a real terminal")
        sys.exit(1)
    cfg = load_config()
    try:
        curses.wrapper(app, cfg)
    except KeyboardInterrupt:
        pass
    finally:
        save_config(cfg)
    print(f"saving songs to: {cfg['download_dir']}")


if __name__ == "__main__":
    main()
