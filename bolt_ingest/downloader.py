import re
from pathlib import Path

from .parser import seconds_to_tag


def _sanitize(name: str) -> str:
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", name)
    name = re.sub(r"\s+", " ", name).strip().strip(".")
    return name[:80] or "clip"


def download_source(src, ingest_dir: Path, tmp_dir: Path, cookies_browser: str = ""):
    """Download one Source (full video or each range). Returns list of temp file paths.

    Always merges to MKV in tmp; postprocess handles making it Premiere-ready.
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
            "outtmpl": outtmpl,
            "merge_output_format": "mkv",   # safe container for any codec; we convert after
            "noplaylist": True,
            "retries": 5,
            "fragment_retries": 5,
            "concurrent_fragment_downloads": 4,
            "restrictfilenames": False,
            "windowsfilenames": True,
            "quiet": False,
            "no_warnings": True,
        }
        if rng:
            opts["download_ranges"] = download_range_func(None, [rng])
            opts["force_keyframes_at_cuts"] = True
        if cookies_browser:
            opts["cookiesfrombrowser"] = (cookies_browser,)

        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(src.url, download=True)
            # resolve actual output path
            if "requested_downloads" in info and info["requested_downloads"]:
                path = Path(info["requested_downloads"][0]["filepath"])
            else:
                path = Path(ydl.prepare_filename(info)).with_suffix(".mkv")
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
