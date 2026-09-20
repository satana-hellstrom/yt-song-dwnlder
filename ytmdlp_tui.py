#!/usr/bin/env python3
"""
ytm-dlp TUI — a terminal UI music downloader built on yt-dlp.

Flow:
  * type a song name (or paste a URL) directly in the top field
  * move up/down with arrow keys to pick container / quality / folder
  * press Enter on "Search & Download" at the bottom
  * watch the "Downloading..." animation, and the saved path is echoed

Requirements on your machine:
  pip install yt-dlp
  ffmpeg installed and on PATH  (needed for audio conversion)

Usage:
  python3 ytmdlp_tui.py
"""

import curses
import json
import os
import queue
import re
import shlex
import subprocess
import sys
import threading
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

# main form rows: (kind, label)
ROW_DEFS = [
    ("entry",     "Song name / URL"),
    ("container", "Container"),
    ("quality",   "Quality"),
    ("folder",    "Save folder"),
    ("meta",      "Embed metadata"),
    ("thumb",     "Embed thumbnail"),
    ("sep",       ""),
    ("go",        "Search & Download"),
]

FIELD_X = 24  # column where values start


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
        "--print", "after_move:SAVED:%(filepath)s",   # echo final path
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
        win.addstr(2, 2, "Enter=ok  Esc=cancel", curses.A_DIM)
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
# Main form
# ---------------------------------------------------------------------------
def draw_main(stdscr, cfg: dict, sel: int, text: str, cursor: int, status: str):
    stdscr.erase()
    h, w = stdscr.getmaxyx()
    title = "~ ytm-dlp ~ terminal music downloader"
    try:
        stdscr.addstr(0, max(0, (w - len(title)) // 2), title,
                      curses.A_BOLD | curses.color_pair(2))
        stdscr.addstr(1, 1, "settings: " + str(CONFIG_FILE), curses.A_DIM)
    except curses.error:
        pass

    values = {
        "container": cfg["container"],
        "quality":   cfg["quality"],
        "folder":    cfg["download_dir"],
        "meta":      toggle(cfg["embed_metadata"]),
        "thumb":     toggle(cfg["embed_thumbnail"]),
    }

    for i, (kind, label) in enumerate(ROW_DEFS):
        row = 3 + i
        focused = (i == sel)
        attr = curses.A_REVERSE if focused else curses.A_NORMAL
        prefix = "> " if focused else "  "
        if kind == "sep":
            try:
                stdscr.hline(row, 2, curses.ACS_HLINE, min(44, w - 4))
            except curses.error:
                pass
            continue
        try:
            stdscr.addstr(row, 2, f"{prefix}{label:<20}", attr)
        except curses.error:
            pass

        if kind == "entry":
            # inline editable field with a visible cursor
            disp = text + " "
            limit = max(4, w - FIELD_X - 2)
            start = 0
            if len(disp) > limit:
                start = max(0, cursor - limit + 1)
            vis = disp[start:start + limit]
            vcur = cursor - start
            for j, c in enumerate(vis):
                cattr = curses.A_REVERSE if (focused and j == vcur) else curses.A_NORMAL
                try:
                    stdscr.addch(row, FIELD_X + j, c, cattr)
                except curses.error:
                    pass
            if not focused:
                try:
                    stdscr.addstr(row, FIELD_X, "", curses.A_NORMAL)
                except curses.error:
                    pass
        elif kind == "go":
            btn = "< Search & Download >"
            battr = curses.A_REVERSE if focused else (curses.A_BOLD | curses.color_pair(2))
            try:
                stdscr.addstr(row, FIELD_X, btn[: w - FIELD_X - 1], battr)
            except curses.error:
                pass
        else:
            try:
                stdscr.addstr(row, FIELD_X, values[kind][: w - FIELD_X - 1], curses.A_DIM)
            except curses.error:
                pass

    if status:
        try:
            stdscr.addstr(h - 2, 1, status[: w - 2], curses.color_pair(1))
        except curses.error:
            pass
    footer = ("type song/URL, Down/Tab next field    "
               if sel == 0 else "up/down move    Enter select    ")
    try:
        stdscr.addstr(h - 1, 1, footer[: w - 2], curses.A_DIM)
    except curses.error:
        pass
    stdscr.refresh()


# ---------------------------------------------------------------------------
# Search flow: animated "Searching..." then a results picker
# ---------------------------------------------------------------------------
def do_search_flow(stdscr, query: str, cfg: dict) -> str:
    res = {}

    def worker():
        res["out"] = search_youtube(query)

    th = threading.Thread(target=worker, daemon=True)
    th.start()

    h, w = stdscr.getmaxyx()
    tick = 0
    while th.is_alive():
        th.join(timeout=0.12)
        tick += 1
        dots = "." * (1 + tick % 3)
        stdscr.erase()
        try:
            stdscr.addstr(h // 2 - 1, 4, f"Searching{dots}", curses.A_BOLD | curses.color_pair(2))
            stdscr.addstr(h // 2 + 1, 4, query[: w - 8], curses.A_DIM)
        except curses.error:
            pass
        stdscr.refresh()

    results, err = res.get("out", (None, "search failed"))
    if err:
        return "search failed: " + err
    if not results:
        return "no results found"

    items = [f"{t[:52]:<52} {c[:16]:<16} {d:>5}" for t, c, d, _ in results]
    idx = pick_from_list(stdscr, f"results for '{query[:30]}'", items)
    if idx is None:
        return "search cancelled"
    return run_download(stdscr, results[idx][3], cfg)


# ---------------------------------------------------------------------------
# Download flow: dots animation, progress bar, echo of saved path
# ---------------------------------------------------------------------------
def run_download(stdscr, url: str, cfg: dict) -> str:
    try:
        os.makedirs(cfg["download_dir"], exist_ok=True)
    except OSError as e:
        return f"cannot create save folder: {e}"
    cmd = build_command(url, cfg)

    h, w = stdscr.getmaxyx()
    stdscr.erase()
    try:
        stdscr.addstr(2, 2, "saving songs in: " + cfg["download_dir"],
                      curses.color_pair(3) | curses.A_BOLD)
        stdscr.addstr(3, 2, url[: w - 3], curses.A_DIM)
        stdscr.addstr(h - 1, 1, "press q to abort", curses.A_DIM)
    except curses.error:
        pass

    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, bufsize=1)
    out_q: queue.Queue = queue.Queue()

    def reader():
        for ln in proc.stdout:
            out_q.put(ln.rstrip("\n"))
        out_q.put(None)  # sentinel: done

    threading.Thread(target=reader, daemon=True).start()

    pct_re = re.compile(r"([0-9.]+)%")
    bar_w = max(10, w - 16)
    info: list = []
    saved = None
    tick = 0
    done = False
    aborted = False

    stdscr.timeout(60)
    try:
        while not done:
            try:
                line = out_q.get(timeout=0.12)
                if line is None:
                    done = True
                    break
            except queue.Empty:
                line = None

            if line is not None:
                if line.startswith("SAVED:"):
                    saved = line[len("SAVED:"):]
                else:
                    m = pct_re.search(line)
                    if m and "%" in line:
                        try:
                            p = min(100.0, float(m.group(1)))
                        except ValueError:
                            p = 0.0
                        filled = int(bar_w * p / 100)
                        bar = "#" * filled + "-" * (bar_w - filled)
                        try:
                            stdscr.addstr(5, 2, f"[{bar}] {p:5.1f}%",
                                          curses.A_BOLD)
                        except curses.error:
                            pass
                    elif line.strip():
                        info.append(line.strip())

            tick += 1
            dots = "." * (1 + (tick // 4) % 3)
            try:
                stdscr.addstr(0, 2, f"Downloading{dots}",
                              curses.A_BOLD | curses.color_pair(2))
            except curses.error:
                pass
            for i, ln in enumerate(info[-4:]):
                try:
                    stdscr.addstr(7 + i, 2, ln[: w - 3], curses.A_DIM)
                except curses.error:
                    pass

            ch = stdscr.getch()
            if ch == ord("q"):
                proc.terminate()
                aborted = True
                break
            stdscr.refresh()
        proc.wait()
    finally:
        stdscr.timeout(-1)

    # result screen — echo where the song was downloaded
    if aborted:
        msg = "aborted by user"
    elif proc.returncode == 0:
        msg = ("Saved to: " + saved) if saved else ("Done -> " + cfg["download_dir"])
    else:
        msg = f"download failed (yt-dlp exit code {proc.returncode})"

    stdscr.erase()
    color = curses.color_pair(2) if (not aborted and proc.returncode == 0) else curses.color_pair(1)
    try:
        stdscr.addstr(h // 2 - 1, 2, msg[: w - 3], curses.A_BOLD | color)
        stdscr.addstr(h // 2 + 1, 2, url[: w - 3], curses.A_DIM)
        stdscr.addstr(h // 2 + 2, 2, "press any key to continue", curses.A_DIM)
    except curses.error:
        pass
    stdscr.refresh()
    stdscr.getch()
    return msg


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

    n = len(ROW_DEFS)
    sel, text, cursor, status = 0, "", 0, ""
    stdscr.keypad(True)

    def move(delta: int):
        nonlocal sel
        while True:
            sel = (sel + delta) % n
            if ROW_DEFS[sel][0] != "sep":
                return

    while True:
        draw_main(stdscr, cfg, sel, text, cursor, status)
        ch = stdscr.getch()
        kind = ROW_DEFS[sel][0]

        if kind == "entry":
            # inline text editing: arrows don't get trapped here
            if ch in (curses.KEY_DOWN, 9, curses.KEY_ENTER, 10, 13):
                move(1)                      # down / Tab / Enter -> next field
            elif ch == curses.KEY_UP:
                move(-1)
            elif ch == curses.KEY_LEFT:
                cursor = max(0, cursor - 1)
            elif ch == curses.KEY_RIGHT:
                cursor = min(len(text), cursor + 1)
            elif ch == curses.KEY_HOME:
                cursor = 0
            elif ch == curses.KEY_END:
                cursor = len(text)
            elif ch in (curses.KEY_BACKSPACE, 127, 8):
                if cursor > 0:
                    text = text[:cursor - 1] + text[cursor:]
                    cursor -= 1
            elif ch == curses.KEY_DC:
                text = text[:cursor] + text[cursor + 1:]
            elif ch == 27:                   # Esc quits from the text field
                return
            elif 32 <= ch < 127:
                text = text[:cursor] + chr(ch) + text[cursor:]
                cursor += 1
            continue

        # rows below the text field
        if ch in (curses.KEY_UP, ord("k")):
            move(-1)
        elif ch in (curses.KEY_DOWN, ord("j")):
            move(1)
        elif ch in (ord("q"), 27):
            return
        elif ch in (curses.KEY_ENTER, 10, 13):
            if kind == "container":
                idx = pick_from_list(stdscr, "audio container",
                                     [f"{name:<12} {desc}" for name, _, desc in CONTAINERS])
                if idx is not None:
                    cfg["container"] = CONTAINERS[idx][0]
            elif kind == "quality":
                idx = pick_from_list(stdscr, "audio quality (bitrate)", QUALITIES)
                if idx is not None:
                    cfg["quality"] = QUALITIES[idx]
            elif kind == "folder":
                got = text_input(stdscr, "folder to save songs in:", cfg["download_dir"])
                if got:
                    cfg["download_dir"] = os.path.expanduser(got)
                    status = "save folder updated"
            elif kind == "meta":
                cfg["embed_metadata"] = not cfg["embed_metadata"]
            elif kind == "thumb":
                cfg["embed_thumbnail"] = not cfg["embed_thumbnail"]
            elif kind == "go":
                q = text.strip()
                if not q:
                    status = "type a song name or URL first"
                elif not have_binary("yt-dlp"):
                    status = "yt-dlp not found - pip install yt-dlp"
                elif not have_binary("ffmpeg"):
                    status = "ffmpeg not found - install it to convert audio"
                elif re.match(r"https?://", q):
                    status = run_download(stdscr, q, cfg)
                else:
                    status = do_search_flow(stdscr, q, cfg)
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
