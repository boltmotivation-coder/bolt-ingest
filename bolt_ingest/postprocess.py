"""Make downloads Premiere-ready.

Logic:
- h264 video  -> remux to MP4 (instant, zero quality loss)
- av1 video   -> remux to MP4 (Premiere 23.3+ decodes AV1; config can force transcode)
- vp9 / other -> transcode to high-quality H.264 (CRF 16), negligible loss pre-Topaz
- opus/vorbis audio -> re-encode to AAC 320k (MP4 + Premiere don't like opus)
"""

import json
import shutil
import subprocess
from pathlib import Path

REMUXABLE_VIDEO = {"h264", "av1"}
MP4_OK_AUDIO = {"aac", "mp3", "alac", "ac3", "eac3"}


def _ffmpeg_paths():
    ff = shutil.which("ffmpeg")
    fp = shutil.which("ffprobe")
    if ff and fp:
        return ff, fp
    try:
        import static_ffmpeg
        print("  First-time setup: downloading ffmpeg (one-off, ~80 MB, a minute or two)...")
        static_ffmpeg.add_paths()
        return shutil.which("ffmpeg"), shutil.which("ffprobe")
    except Exception:
        return ff, fp


def probe(path: Path):
    _, ffprobe = _ffmpeg_paths()
    r = subprocess.run(
        [ffprobe, "-v", "error", "-show_entries",
         "stream=codec_type,codec_name,width,height", "-of", "json", str(path)],
        capture_output=True, text=True,
    )
    vcodec = acodec = ""
    width = height = 0
    try:
        for s in json.loads(r.stdout).get("streams", []):
            if s.get("codec_type") == "video" and not vcodec:
                vcodec = s.get("codec_name", "")
                width, height = s.get("width", 0), s.get("height", 0)
            elif s.get("codec_type") == "audio" and not acodec:
                acodec = s.get("codec_name", "")
    except Exception:
        pass
    return vcodec, acodec, width, height


def make_premiere_ready(tmp_path: Path, ingest_dir: Path, source_url: str = "",
                        final_stem: str = None, overwrite: bool = False):
    """Returns (final_path, action, vcodec, resolution).

    final_stem: clean output name (no extension). overwrite=True replaces an
    existing file of the same name (used when re-grabbing at better quality).
    """
    ffmpeg, _ = _ffmpeg_paths()
    vcodec, acodec, w, h = probe(tmp_path)
    stem = final_stem or tmp_path.stem
    final = ingest_dir / f"{stem}.mp4"
    if not overwrite:
        i = 1
        while final.exists():
            final = ingest_dir / f"{stem} ({i}).mp4"
            i += 1

    audio_args = ["-c:a", "copy"] if acodec in MP4_OK_AUDIO else ["-c:a", "aac", "-b:a", "320k"]
    # source url travels inside the file, so any clip in Premiere can be traced back
    meta_args = ["-metadata", f"comment={source_url}"] if source_url else []

    if vcodec in REMUXABLE_VIDEO:
        action = "remux"
        cmd = [ffmpeg, "-y", "-v", "error", "-i", str(tmp_path),
               "-c:v", "copy", *audio_args, *meta_args,
               "-movflags", "+faststart", str(final)]
    else:
        action = f"transcode ({vcodec or 'unknown'} -> h264)"
        print(f"  Converting {vcodec or 'unknown'} -> H.264 for Premiere "
              "(normal for YouTube 4K; can take a few minutes on long clips)...")
        cmd = [ffmpeg, "-y", "-v", "error", "-i", str(tmp_path),
               "-c:v", "libx264", "-crf", "16", "-preset", "fast",
               "-pix_fmt", "yuv420p", *audio_args, *meta_args,
               "-movflags", "+faststart", str(final)]

    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0 or not final.exists():
        # last resort: hand over the raw file so footage is never lost
        fallback = ingest_dir / tmp_path.name
        shutil.move(str(tmp_path), str(fallback))
        return fallback, "kept original (convert failed)", vcodec, f"{w}x{h}"

    tmp_path.unlink(missing_ok=True)
    return final, action, vcodec, f"{w}x{h}"
