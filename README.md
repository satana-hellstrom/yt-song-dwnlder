# yt-song-dwnlder

A terminal UI (TUI) music downloader built on [yt-dlp](https://github.com/yt-dlp/yt-dlp).

Search or paste a link, pick your audio container and quality, and download — all from the terminal.

## Features

- **Search or paste** — type a plain search query (YouTube search, pick from top 10 results) or paste any supported URL
- **Containers** — MP3, M4A/AAC, Opus, FLAC, WAV, OGG Vorbis, or Best (native stream, no re-encode)
- **Quality** — best / 320k / 256k / 192k / 128k
- **Save folder** — read from `~/.config/ytmdlp-tui/config.json`, editable in the UI, remembered between runs
- **Embed metadata & thumbnail** — toggle on/off
- **Live progress bar** — abort with `q`

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
| ↑ / ↓ (or k / j) | move |
| Enter | select / edit |
| q | quit (or abort a download) |

## Notes

- "Best" keeps YouTube's native (Opus) stream — same audio quality as 320k MP3 at a smaller size. FLAC/WAV re-encode losslessly but cannot restore quality that was never uploaded.
- Windows users: run under WSL (the Windows console has limited `curses` support).

## License

MIT
