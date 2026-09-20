# yt-song-dwnlder

A terminal UI music downloader written in **pure bash** on top of [yt-dlp](https://github.com/yt-dlp/yt-dlp) — no Python, no dependencies beyond yt-dlp and ffmpeg.

Type a song name or paste a link in the boxed field at the top, move down with arrow keys to pick your container and quality, then hit the Search & Download button.

## Features

- **Boxed URL / song entry field** — `Song name / URL [ ................ ]`, typed directly on the form; arrows and Tab move between fields, ←/→ move the text cursor
- **Search results list** — shows up to 10 similar songs with channel and duration; pick with arrow keys, Enter downloads, `q` goes back to the search page to search again
- **Containers** — MP3, M4A/AAC, Opus, FLAC, WAV, OGG Vorbis, or Best (native stream, no re-encode)
- **Quality** — best / 320k / 256k / 192k / 128k
- **Save folder** — read from `~/.config/yt-song-dwnlder/config.sh`, editable in its own box, remembered between runs
- **Embed metadata & thumbnail** — toggle on/off
- **Loading** — animated `Searching...` / `Downloading...` dots with a live progress bar
- **Echoes the saved path** — after each download it shows exactly which file was saved and where, then returns to the results list so you can grab another song

## Requirements

- bash 4+ (Linux/macOS default)
- [yt-dlp](https://github.com/yt-dlp/yt-dlp): `pip install yt-dlp`
- ffmpeg (needed for audio conversion): e.g. `sudo apt install ffmpeg`

## Usage

```bash
chmod +x yt-song-dwnlder.sh
./yt-song-dwnlder.sh
```

| Key | Action |
|-----|--------|
| (just type) | edit the boxed field (song name / URL / folder) |
| ← / → | move the text cursor inside a box |
| ↓ / Tab / Enter | next field (from a boxed field) |
| ↑ / ↓ | move between fields / results |
| Enter | change the selected setting · download the selected result |
| q | back to search page (in results) · quit (on the form) |
| Esc | quit |
| Ctrl-C | abort a running download |

## Notes

- "Best" keeps YouTube's native (Opus) stream — same audio quality as 320k MP3 at a smaller size. FLAC/WAV re-encode losslessly but cannot restore quality that was never uploaded.
- Runs in the alternate screen buffer; your shell history stays clean when you quit.

## License

MIT
