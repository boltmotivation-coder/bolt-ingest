"""Pull the script/transcript of a video.

Strategy (cheapest first):
1. Platform captions (manual subs preferred, then auto-captions) via yt-dlp.
   Free, instant, no video download needed. Auto-captions arrive as rolling
   overlapping fragments, so they get deduped and reflowed into real lines.
2. Local Whisper (faster-whisper) on an audio-only download when the platform
   has no captions (TikTok / Instagram / most reels). No API keys; the model
   is fetched once on first use.

Output, dropped in ingest next to the clip:
    <Title> [<id>].txt   readable, timestamped dialog lines
"""

import json
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

from .downloader import _sanitize

# --------------------------------------------------------------------------
# caption fetching
# --------------------------------------------------------------------------

_PREFERRED_EXTS = ("json3", "vtt", "srv3", "srv1", "ttml")


def _pick_track(pool: dict):
    """Pick the best language track from a subtitles/automatic_captions dict."""
    if not pool:
        return None
    # prefer English variants, then an "orig" track, then whatever is first
    keys = sorted(pool.keys(), key=lambda k: (
        0 if k.lower().startswith("en") else (1 if "orig" in k.lower() else 2), k))
    for key in keys:
        formats = pool[key] or []
        for ext in _PREFERRED_EXTS:
            for f in formats:
                if f.get("ext") == ext and f.get("url"):
                    return f
        if formats and formats[0].get("url"):
            return formats[0]
    return None


def _download_track(track):
    req = urllib.request.Request(track["url"], headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=15) as r:
        data = r.read().decode("utf-8", "ignore")
    if track.get("ext") == "json3":
        return _parse_json3(data)
    return _parse_vtt(data)


def _parse_json3(data: str):
    segs = []
    try:
        events = json.loads(data).get("events", [])
    except Exception:
        return []
    for ev in events:
        if "segs" not in ev:
            continue
        text = "".join(s.get("utf8", "") for s in ev["segs"])
        text = re.sub(r"\s+", " ", text).strip()
        if not text:
            continue
        start = ev.get("tStartMs", 0) / 1000.0
        dur = ev.get("dDurationMs", 0) / 1000.0
        segs.append([start, start + dur, text])
    return _dedupe(segs)


_VTT_TIME = r"(?:(\d+):)?(\d{1,2}):(\d{2})[.,](\d{3})"
_VTT_CUE = re.compile(rf"{_VTT_TIME}\s*-->\s*{_VTT_TIME}")


def _vtt_secs(h, m, s, ms):
    return int(h or 0) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000.0


def _parse_vtt(data: str):
    segs = []
    prev_lines = set()
    cur = None  # [start, end, lines]
    for raw in data.splitlines():
        m = _VTT_CUE.search(raw)
        if m:
            if cur and cur[2]:
                segs.append([cur[0], cur[1], " ".join(cur[2])])
                prev_lines = set(cur[2])
            g = m.groups()
            cur = [_vtt_secs(*g[:4]), _vtt_secs(*g[4:]), []]
            continue
        if cur is None:
            continue
        line = re.sub(r"<[^>]+>", "", raw).strip()
        if not line or line.isdigit() or line.upper().startswith(("WEBVTT", "NOTE", "STYLE", "Kind:", "Language:")):
            continue
        # rolling auto-captions repeat the previous cue's line; drop those
        if line in prev_lines:
            continue
        cur[2].append(line)
    if cur and cur[2]:
        segs.append([cur[0], cur[1], " ".join(cur[2])])
    return _dedupe(segs)


def _dedupe(segs):
    out = []
    for s in segs:
        if out and s[2] == out[-1][2]:
            out[-1][1] = max(out[-1][1], s[1])
            continue
        out.append(s)
    return out


def fetch_captions(url: str, cookies_browser: str = ""):
    """Returns (segments, method, info). segments is None if the platform has none."""
    import yt_dlp

    opts = {
        "skip_download": True,
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        # YouTube's default web clients hide subtitles behind a PO token;
        # the android/ios clients still hand them out
        "extractor_args": {"youtube": {"player_client": ["android", "ios"]}},
    }
    if cookies_browser:
        opts["cookiesfrombrowser"] = (cookies_browser,)
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)

    for method, pool in (("captions", info.get("subtitles") or {}),
                         ("auto-captions", info.get("automatic_captions") or {})):
        track = _pick_track(pool)
        if not track:
            continue
        try:
            segs = _download_track(track)
        except Exception:
            continue
        if segs:
            return segs, method, info
    return None, "", info


# --------------------------------------------------------------------------
# whisper fallback
# --------------------------------------------------------------------------

def _ensure_faster_whisper():
    try:
        import faster_whisper  # noqa: F401
        return True
    except ImportError:
        pass
    print("  First-time setup: installing faster-whisper (one-off, ~100 MB, a minute or two)...")
    cmds = [
        [sys.executable, "-m", "pip", "install", "-q", "faster-whisper"],
        ["pipx", "inject", "bolt-ingest", "faster-whisper"],
    ]
    for cmd in cmds:
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
            if r.returncode == 0:
                break
        except FileNotFoundError:
            continue
        except Exception:
            break
    try:
        import faster_whisper  # noqa: F401
        return True
    except ImportError:
        return False


def _download_audio(url: str, tmp_dir: Path, cookies_browser: str = ""):
    import yt_dlp

    opts = {
        "format": "ba/b",
        "outtmpl": str(tmp_dir / "audio_%(id)s.%(ext)s"),
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "retries": 5,
        # audio for transcription only; mobile clients dodge YouTube bot checks
        "extractor_args": {"youtube": {"player_client": ["android", "ios"]}},
    }
    if cookies_browser:
        opts["cookiesfrombrowser"] = (cookies_browser,)
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
        if "requested_downloads" in info and info["requested_downloads"]:
            return Path(info["requested_downloads"][0]["filepath"])
        return Path(ydl.prepare_filename(info))


def whisper_transcribe(url: str, tmp_dir: Path, cfg):
    if not _ensure_faster_whisper():
        raise RuntimeError(
            "Could not install faster-whisper automatically. "
            "Run: pipx inject bolt-ingest faster-whisper"
        )
    from faster_whisper import WhisperModel

    print("  Downloading the audio track for transcription...")
    audio = _download_audio(url, tmp_dir, cfg.get("cookies_browser", ""))
    model_name = cfg.get("whisper_model", "small")
    print(f"  Transcribing locally with Whisper ({model_name})... "
          "(first run downloads the model once, ~500 MB; transcribing runs at "
          "roughly the video's own length)")
    model = WhisperModel(model_name, device="auto", compute_type="int8")
    segments, _ = model.transcribe(str(audio), vad_filter=True)
    segs = [[s.start, s.end, s.text.strip()] for s in segments if s.text.strip()]
    audio.unlink(missing_ok=True)
    return segs


# --------------------------------------------------------------------------
# formatting + entry point
# --------------------------------------------------------------------------

def _ts(sec: float) -> str:
    sec = int(sec)
    m, s = divmod(sec, 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def format_txt(segs, title: str, url: str, method: str) -> str:
    """Timestamped dialog lines: new line on a pause (>2s) or when a line gets long."""
    paras = []
    cur, cur_start, last_end = [], 0.0, None
    for start, end, text in segs:
        if cur and (start - last_end > 2.0 or sum(len(t) for t in cur) > 320):
            paras.append((cur_start, " ".join(cur)))
            cur = []
        if not cur:
            cur_start = start
        cur.append(text)
        last_end = end
    if cur:
        paras.append((cur_start, " ".join(cur)))

    head = [title, f"Source: {url}", f"Transcript via {method}", ""]
    body = [f"[{_ts(t)}]  {text}" for t, text in paras]
    return "\n".join(head + body) + "\n"


def fetch_script(src, ingest_dir: Path, tmp_dir: Path, cfg):
    """Get the transcript for one Source. Returns (txt_path, method).

    The .txt is named after the video so it sits right next to the clip.
    """
    print(f"  Checking for platform captions ({src.url})...")
    segs, method, info = fetch_captions(src.url, cfg.get("cookies_browser", ""))
    if not segs:
        print("  No captions on the platform — falling back to local Whisper.")
        segs = whisper_transcribe(src.url, tmp_dir, cfg)
        method = "whisper (local)"
    if not segs:
        raise RuntimeError("No speech found in this video.")

    title = info.get("title", "clip")
    vid = info.get("id", "")
    base = _sanitize(f"{title} [{vid}]" if vid else title)
    txt_path = ingest_dir / f"{base}.txt"
    txt_path.write_text(format_txt(segs, title, src.url, method), encoding="utf-8")
    return txt_path, method
