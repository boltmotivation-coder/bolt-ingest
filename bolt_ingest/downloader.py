import re
import threading
from contextlib import contextmanager
from pathlib import Path

from .parser import seconds_to_tag


@contextmanager
def _section_heartbeat(tmp_dir: Path, interval: int = 15):
    """Section grabs go through ffmpeg, which prints nothing - the terminal
    sits silent for minutes and people assume bolt died. Poll the tmp folder
    size so there's a visible sign of life."""
    stop = threading.Event()

    def _watch():
        last = -1
        while not stop.wait(interval):
            try:
                size = sum(f.stat().st_size for f in tmp_dir.iterdir() if f.is_file())
            except OSError:
                continue
            mb = size / 1_000_000
            if size > last:
                print(f"  ...still downloading - {mb:.0f} MB so far (no progress bar on sections; "
                      "clips appear in the ingest folder when finished)")
            else:
                print(f"  ...still working ({mb:.0f} MB so far) - if this line repeats for several "
                      "minutes with the same number, Ctrl+C and rerun bolt")
            last = size

    t = threading.Thread(target=_watch, daemon=True)
    t.start()
    try:
        yield
    finally:
        stop.set()
        t.join(timeout=2)


def _sanitize(name: str) -> str:
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", name)
    name = re.sub(r"\s+", " ", name).strip().strip(".")
    return name[:80] or "clip"


def best_available_height(url: str, cookies_browser: str = "") -> int:
    """Highest video height the platform offers right now (0 if unknown)."""
    import yt_dlp

    opts = {"quiet": True, "no_warnings": True, "noplaylist": True, "skip_download": True}
    if cookies_browser:
        opts["cookiesfrombrowser"] = (cookies_browser,)
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
        heights = [f.get("height") or 0 for f in info.get("formats") or []]
        return max(heights) if heights else int(info.get("height") or 0)
    except Exception:
        return 0


def download_source(src, ingest_dir: Path, tmp_dir: Path, cookies_browser: str = "",
                    handle_seconds: int = 0):
    """Download one Source (full video or each range). Returns list of temp file paths.

    Always merges to MKV in tmp; postprocess handles making it Premiere-ready.
    handle_seconds pads each requested range so editors get trim handles.
    """
    import yt_dlp
    from yt_dlp.utils import download_range_func

    results = []
    jobs = src.ranges if src.ranges else [None]

    for rng in jobs:
        tag = f" [{seconds_to_tag(rng[0])}-{seconds_to_tag(rng[1])}]" if rng else ""
        outtmpl = str(tmp_dir / f"%(title).70s [%(id)s]{tag}.%(ext)s")

        opts = {
            "format": "bv*+ba/b",           # true best video + best audio, no exceptions
            # prefer the highest-bitrate variant at the top resolution (grabs
            # YouTube's premium-bitrate formats when they exist)
            "format_sort": ["res", "fps", "hdr:12", "br"],
            "outtmpl": outtmpl,
            "merge_output_format": "mkv",   # safe container for any codec; we convert after
            "noplaylist": True,
            "retries": 5,
            "fragment_retries": 5,
            "concurrent_fragment_downloads": 8,
            "restrictfilenames": False,
            "windowsfilenames": True,
            "quiet": False,
            "no_warnings": True,
        }
        if rng:
            padded = (max(0, rng[0] - handle_seconds), rng[1] + handle_seconds)
            opts["download_ranges"] = download_range_func(None, [padded])
            opts["force_keyframes_at_cuts"] = True
            print(f"  Grabbing section {seconds_to_tag(rng[0])}-{seconds_to_tag(rng[1])} "
                  "(sections need clean cut points, so this takes longer than the clip length).\n"
                  "  Heads up: sections show no progress bar - bolt will report in every 15s so "
                  "you know it's alive...")
        if cookies_browser:
            opts["cookiesfrombrowser"] = (cookies_browser,)

        def _grab(o):
            with yt_dlp.YoutubeDL(o) as ydl:
                inf = ydl.extract_info(src.url, download=True)
                if inf.get("requested_downloads"):
                    p = Path(inf["requested_downloads"][0]["filepath"])
                else:
                    p = Path(ydl.prepare_filename(inf)).with_suffix(".mkv")
            return inf, p

        from contextlib import nullcontext

        def _beat():
            return _section_heartbeat(tmp_dir) if rng else nullcontext()

        try:
            with _beat():
                info, path = _grab(opts)
        except Exception as e:
            # YouTube bot-checks some networks (403 / "page needs to be reloaded");
            # the android/ios clients usually still work, so retry through them
            msg = str(e)
            retriable = ("403" in msg or "Forbidden" in msg
                         or "needs to be reloaded" in msg or "Sign in to confirm" in msg
                         or "ffmpeg exited" in msg)  # range fetches surface the 403 this way
            if not retriable or "youtu" not in src.url.lower():
                raise
            # mid-download 403s are usually expired/rotated stream URLs; a plain
            # retry with fresh URLs keeps full quality, so try that first
            print("  Blocked by YouTube mid-download - retrying with fresh stream URLs...")
            try:
                with _beat():
                    info, path = _grab(opts)
            except Exception:
                print("  Still blocked - falling back to mobile clients (may cap the resolution)...")
                with _beat():
                    info, path = _grab({**opts, "extractor_args": {"youtube": {"player_client": ["android", "ios"]}}})
                h = info.get("height") or 0
                if h and h < 720:
                    print(f"  WARNING: only got {h}p for this one - YouTube limited the backup route. "
                          "Rerun bolt on this link later (or after a VPN switch) for full quality.")

        results.append({
            "path": path,
            "title": info.get("title", "clip"),
            "id": info.get("id", ""),
            "range": rng,
            "source_url": src.url,
            "notes": src.notes,
            "extractor": info.get("extractor_key", ""),
        })
    return results
