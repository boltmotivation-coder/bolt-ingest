# bolt

Bolt Motivation footage ingest tool. Paste Aaradhya's research block from Notion, get best-quality Premiere-ready clips in your `ingest` folder. No 4K Video Downloader, no MP4 vs MKV guessing, no manual converting.

## Install (once)

**Mac** — open Terminal, paste:
```
curl -fsSL https://raw.githubusercontent.com/boltmotivation-coder/bolt-ingest/main/install.sh | bash
```

**Windows** — open PowerShell, paste:
```
irm https://raw.githubusercontent.com/boltmotivation-coder/bolt-ingest/main/install.ps1 | iex
```

Then close the terminal, open a new one, and type `bolt`. First run asks where your ingest folder is.

## Daily use

1. Open Terminal / PowerShell
2. Type `bolt`, hit Enter
3. Copy the whole **Sources & Footage** section from Notion, paste it, hit Enter
4. Confirm the preview, let it run

That's it. Every clip lands in `ingest/` as a Premiere-ready MP4 at the highest quality that exists for that video.

## What it does under the hood

- Always downloads the true best video + audio streams (yt-dlp), on YouTube, TikTok, Instagram, and ~1800 other sites
- `00:00-00:00` timestamps = full video. Real ranges = only those sections get downloaded
- Auto-converts anything Premiere can't read (VP9 -> high-quality H.264, opus audio -> AAC). H.264/AV1 sources are remuxed losslessly
- Updates itself and yt-dlp automatically, you never reinstall anything
- Writes a manifest of every pull to `ingest/_manifests/`

## Commands

```
bolt              paste mode (the normal way)
bolt block.txt    read the research block from a file
bolt --dry-run    preview what would be downloaded, download nothing
bolt config       change ingest folder / webhook / Instagram cookies
```

## Instagram

Instagram needs you to be logged in. Run `bolt config`, option 3, and enter the browser where you're signed into IG (e.g. `chrome`). bolt reads the login cookies from there automatically.
