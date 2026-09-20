# yt-song-dwnlder

A terminal UI (TUI) music downloader built on [yt-dlp](https://github.com/yt-dlp/yt-dlp).

Type a song name or paste a link in the top field, move down with arrow keys to pick your container and quality, then hit the Search & Download button — all from the terminal.

## Features

- **Inline entry field** — type a song name (YouTube search, pick from top 10 results) or paste any supported URL; arrow keys always work, no modal trapping input
- **Containers** — MP3, M4A/AAC, Opus, FLAC, WAV, OGG Vorbis, or Best (native stream, no re-encode)
- **Quality** — best / 320k / 256k / 192k / 128k
- **Save folder** — read from `~/.config/ytmdlp-tui/config.json`, editable in the UI, remembered between runs
- **Embed metadata & thumbnail** — toggle on/off
- **Loading animation** — "Searching..." / "Downloading..." with live progress bar, abort with `q`
- **Echoes the saved path** — shows exactly which file was downloaded and where

## Requirements

- Python 3.10+
- yt-dlp: `pip install yt-dlp`
- ffmpeg (needed for audio conversion) — e.g. `sudo apt install ffmpeg` on Debian/Ubuntu

## Usage

```bash
python3 ytmdlp_tui.py
```

| Key | Action |
|-----|--------|
| (just type) | enter song name / URL in the top field |
| ← / → | move the text cursor |
| ↓ / Tab / Enter | next field (from the entry field) |
| ↑ / ↓ | move between fields |
| Enter | change the selected setting |
| q / Esc | quit (or abort a download) |

## Notes

- "Best" keeps YouTube's native (Opus) stream — same audio quality as 320k MP3 at a smaller size. FLAC/WAV re-encode losslessly but cannot restore quality that was never uploaded.
- Windows users: run under WSL (the Windows console has limited `curses` support).

## License

MIT
