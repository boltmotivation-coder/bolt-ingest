import re
import sys
from pathlib import Path

from .parser import seconds_to_tag

# Section grabs are fetched in bounded HTTP chunks. Each chunk is a fresh Range
# request, so a stalled read trips socket_timeout and retries instead of one
# giant streamed read wedging forever over a flaky VPN.
HTTP_CHUNK = 10_000_000  # 10 MB

# Watchdog: if the tmp folder hasn't grown at all for this long, the grab is
# genuinely stuck (VPN stall). Kill it and let the retry logic take over.
HEARTBEAT_INTERVAL = 15   # seconds between "still alive" prints
STALL_KILL = 90           # seconds of zero progress before we abort the grab


def _reconfigure_utf8():
    # Windows defaults stdout to cp1252, which explodes on emoji in video titles.
    # main() does this for the parent; a spawned worker is a fresh process and
    # must redo it or yt-dlp's title prints crash the child.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


def _download_worker(q, opts, url, padded):
    """Runs in a spawned subprocess so a wedged socket can be force-killed from
    the parent (you can't kill a socket-blocked thread on Windows). Rebuilds the
    non-picklable download_ranges closure here, then reports a small result dict
    back over the queue."""
    try:
        _reconfigure_utf8()
        import yt_dlp
        from yt_dlp.utils import download_range_func

        o = dict(opts)
        o["download_ranges"] = download_range_func(None, [tuple(padded)])
        with yt_dlp.YoutubeDL(o) as ydl:
            inf = ydl.extract_info(url, download=True)
            if inf.get("requested_downloads"):
                path = inf["requested_downloads"][0]["filepath"]
            else:
                path = str(Path(ydl.prepare_filename(inf)).with_suffix(".mkv"))
        q.put({
            "ok": True,
            "path": path,
            "title": inf.get("title", "clip"),
            "id": inf.get("id", ""),
            "height": inf.get("height") or 0,
            "extractor_key": inf.get("extractor_key", ""),
        })
    except Exception as e:  # surface the real error to the parent for retry logic
        try:
            q.put({"ok": False, "error": str(e)})
        except Exception:
            pass


def _grab_section_watched(opts, url, padded, tmp_dir):
    """Download one section in a subprocess, watching the tmp folder for signs of
    life. Prints a heartbeat every 15s (sections have no progress bar). If the
    folder stops growing for STALL_KILL seconds the grab is wedged, so we kill it
    and raise so the caller can retry / fall back to mobile clients."""
    import multiprocessing as mp

    ctx = mp.get_context("spawn")
    q = ctx.Queue()
    proc = ctx.Process(target=_download_worker, args=(q, opts, url, list(padded)),
                       daemon=True)
    proc.start()

    last = -1
    zero_growth = 0
    try:
        while True:
            proc.join(timeout=HEARTBEAT_INTERVAL)  # returns early if it finishes
            try:
                size = sum(f.stat().st_size for f in tmp_dir.iterdir() if f.is_file())
            except OSError:
                size = last
            mb = size / 1_000_000

            if not proc.is_alive():
                break  # done (or died) - go read the result

            if size > last:
                zero_growth = 0
                print(f"  ...still downloading - {mb:.0f} MB so far (clips appear in the "
                      "ingest folder when finished)")
            else:
                zero_growth += HEARTBEAT_INTERVAL
                if zero_growth >= STALL_KILL:
                    print(f"  ...no data for {zero_growth}s - VPN stall, aborting this "
                          "grab and retrying automatically (no need to touch anything)...")
                    proc.terminate()
                    proc.join(timeout=5)
                    raise TimeoutError("section download stalled (0 bytes) - aborted by watchdog")
                print(f"  ...still working ({mb:.0f} MB so far)...")
            last = size
    finally:
        if proc.is_alive():
            proc.terminate()
            proc.join(timeout=5)

    try:
        result = q.get(timeout=5)
    except Exception:
        result = None
    if not result or not result.get("ok"):
        raise RuntimeError((result or {}).get("error") or "section download failed (worker died)")

    result["path"] = Path(result["path"])
    return result


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
            # fetch in bounded chunks so a stalled read on a flaky VPN trips the
            # socket timeout and retries instead of one endless streamed read
            "http_chunk_size": HTTP_CHUNK,
            # a stalled socket over a flaky VPN must error out (and hit the retry
            # logic) instead of hanging the whole download forever
            "socket_timeout": 30,
            "restrictfilenames": False,
            "windowsfilenames": True,
            "quiet": False,
            "no_warnings": True,
        }
        padded = None
        if rng:
            padded = (max(0, rng[0] - handle_seconds), rng[1] + handle_seconds)
            # NOTE: deliberately NOT setting force_keyframes_at_cuts. That flag
            # routes the section fetch through an ffmpeg subprocess that reads the
            # stream directly with no read timeout - over a high-latency VPN it
            # stalls forever at 0 bytes. Native range download only grabs the
            # fragments overlapping the range, honors socket_timeout/retries, and
            # is run under a watchdog (see _grab_section_watched) that kills and
            # retries any grab that still wedges. Cuts land on keyframes instead
            # of frame-exact, but every range is padded with handles, so editors
            # trim clean.
            print(f"  Grabbing section {seconds_to_tag(rng[0])}-{seconds_to_tag(rng[1])} "
                  "(downloads just this slice; no progress bar, so bolt reports in "
                  "every 15s to show it's alive)...")
        if cookies_browser:
            opts["cookiesfrombrowser"] = (cookies_browser,)

        def _grab(o):
            # sections run in a killable subprocess under the stall watchdog;
            # full downloads have a live progress bar, so run them in-process
            if padded is not None:
                return _grab_section_watched(o, src.url, padded, tmp_dir)
            with yt_dlp.YoutubeDL(o) as ydl:
                inf = ydl.extract_info(src.url, download=True)
                if inf.get("requested_downloads"):
                    p = Path(inf["requested_downloads"][0]["filepath"])
                else:
                    p = Path(ydl.prepare_filename(inf)).with_suffix(".mkv")
            return {
                "path": p,
                "title": inf.get("title", "clip"),
                "id": inf.get("id", ""),
                "height": inf.get("height") or 0,
                "extractor_key": inf.get("extractor_key", ""),
            }

        try:
            meta = _grab(opts)
        except Exception as e:
            # YouTube bot-checks some networks (403 / "page needs to be reloaded");
            # the android/ios clients usually still work, so retry through them.
            # A watchdog-aborted VPN stall lands here too and is fully retriable.
            msg = str(e)
            low = msg.lower()
            retriable = ("403" in msg or "Forbidden" in msg
                         or "needs to be reloaded" in msg or "Sign in to confirm" in msg
                         or "ffmpeg exited" in msg  # range fetches surface the 403 this way
                         or "stalled" in low or "timed out" in low or "timeout" in low)  # VPN stalls
            if not retriable or "youtu" not in src.url.lower():
                raise
            # mid-download 403s are usually expired/rotated stream URLs, and a
            # watchdog kill just needs a fresh attempt; a plain retry keeps full
            # quality, so try that first
            print("  Stalled or blocked mid-download - retrying with fresh stream URLs...")
            try:
                meta = _grab(opts)
            except Exception:
                print("  Still failing - falling back to mobile clients (may cap the resolution)...")
                meta = _grab({**opts, "extractor_args": {"youtube": {"player_client": ["android", "ios"]}}})
                h = meta.get("height") or 0
                if h and h < 720:
                    print(f"  WARNING: only got {h}p for this one - YouTube limited the backup route. "
                          "Rerun bolt on this link later (or after a VPN switch) for full quality.")

        results.append({
            "path": meta["path"],
            "title": meta.get("title", "clip"),
            "id": meta.get("id", ""),
            "range": rng,
            "source_url": src.url,
            "notes": src.notes,
            "extractor": meta.get("extractor_key", ""),
        })
    return results
