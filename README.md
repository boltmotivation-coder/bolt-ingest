# bolt

Bolt Motivation footage ingest tool. Paste the research block from Notion, get best-quality Premiere-ready clips in your `ingest` folder. No 4K Video Downloader, no MP4 vs MKV guessing, no manual converting.

## Install (once)

**Mac** — open Terminal, paste:
```
curl -fsSL https://raw.githubusercontent.com/boltmotivation-coder/bolt-ingest/main/install.sh | bash
```

**Windows** — open PowerShell, paste:
```
irm https://raw.githubusercontent.com/boltmotivation-coder/bolt-ingest/main/install.ps1 | iex
```

Then close the terminal, open a new one, and type `bolt`. On first run it looks for the recommended layout and offers it — just hit Enter. If you don't have it yet, bolt offers to set it up for you.

### Recommended folder layout

```
Documents/
    Working Folder/
        INGEST/     <- everything bolt downloads (safe to clear out anytime)
        PROJECTS/   <- your actual Premiere projects
```

bolt looks for `Documents/Working Folder/INGEST` first. If you keep your ingest folder somewhere else, it'll still find a folder named `INGEST`/`ingest` under Documents, Desktop, Downloads, or Movies and offer that instead.

**Don't care about the layout?** On first run you can just press `d` to use your Downloads folder, or type/paste/drag any folder you want. Change it later anytime with `bolt config` → option 1 (you can drag a folder straight into the Terminal there too).

## Daily use

1. Open Terminal / PowerShell
2. Type `bolt`, hit Enter
3. Copy the whole **Sources & Footage** section from Notion, paste it, hit Enter
4. Confirm the preview, let it run

That's it. Every clip lands in `ingest/` as a Premiere-ready MP4 at the highest quality that exists for that video.

**The very first run is slower than normal** — bolt fetches its own ffmpeg (~80 MB) and, the first time a video has no captions, the Whisper transcription model (~500 MB). It says so on screen when it happens; after that everything is cached and fast. Also normal: 4K YouTube clips convert to H.264 after downloading (a few minutes for long ones), and timestamped sections take longer than their length suggests because bolt cuts them on clean frames.

Shortcuts: if the links are already in your clipboard, `bolt` offers them automatically. You can also skip paste mode entirely: `bolt https://youtu.be/xxxx https://tiktok.com/...`

## Transcript on every download

Every clip gets a matching `Title [id].txt` right next to it — a clean, timestamped, readable transcript of the video. No extra command, it just happens.

It grabs the platform's captions when they exist (instant, free). If there are none (TikTok, IG, most reels), it transcribes locally with Whisper — no API keys, nothing to set up; the model downloads once on first use. If a video has no speech at all, it just skips the transcript and keeps the clip.

## What it does under the hood

- Always downloads the true best video + audio streams (yt-dlp), on YouTube, TikTok, Instagram, and ~1800 other sites — sorted to prefer the highest-bitrate variant at the top resolution
- `00:00-00:00` timestamps = full video. Real ranges = only those sections get downloaded, padded with 2s trim handles on each side (change in `bolt config`)
- Auto-converts anything Premiere can't read (VP9 -> high-quality H.264, opus audio -> AAC). H.264/AV1 sources are remuxed losslessly
- Drops a readable `.txt` transcript next to every clip (captions when they exist, local Whisper otherwise)
- Embeds the source URL in each MP4's metadata, so any clip in Premiere can be traced back
- Updates itself and yt-dlp automatically, you never reinstall anything
- Writes a manifest of every pull to `ingest/_manifests/`

## Commands

```
bolt                    paste mode (the normal way; offers clipboard contents if links are there)
bolt <url> [<url>...]   download links directly, no pasting
bolt block.txt          read the research block from a file
bolt --dry-run          preview what would be downloaded, download nothing
bolt config             ingest folder / webhook / cookies / handles / whisper model
```

## Instagram

Instagram needs you to be logged in. Run `bolt config`, option 3, and enter the browser where you're signed into IG (e.g. `chrome`). bolt reads the login cookies from there automatically.
