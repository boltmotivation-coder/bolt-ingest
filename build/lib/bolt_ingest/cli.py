import argparse
import os
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path

from . import __version__
from . import config as cfg_mod
from .parser import parse_block, seconds_to_tag, URL_RE


class _StdinReader:
    """Single owner of stdin so paste detection and prompts don't fight over it."""

    def __init__(self):
        self.q = queue.Queue()
        self.eof = False
        t = threading.Thread(target=self._pump, daemon=True)
        t.start()

    def _pump(self):
        for line in sys.stdin:
            self.q.put(line)
        self.q.put(None)

    def readline(self, timeout=None):
        if self.eof:
            return None
        try:
            item = self.q.get(timeout=timeout)
        except queue.Empty:
            return ""
        if item is None:
            self.eof = True
            return None
        return item

    def ask(self, prompt):
        print(prompt, end="", flush=True)
        line = self.readline()
        return (line or "").strip()


def _read_clipboard():
    try:
        if sys.platform == "darwin":
            cmd = ["pbpaste"]
        elif os.name == "nt":
            cmd = ["powershell", "-noprofile", "-command", "Get-Clipboard"]
        else:
            cmd = ["xclip", "-selection", "clipboard", "-o"]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=3)
        return r.stdout if r.returncode == 0 else ""
    except Exception:
        return ""


def clipboard_or_paste(reader):
    """If the clipboard already holds links (or the whole Notion block), offer it."""
    clip = _read_clipboard()
    n = len(URL_RE.findall(clip))
    if n:
        ans = reader.ask(
            f"\nFound {n} link(s) in your clipboard. Use that? [Enter = yes / n = paste manually]: "
        ).lower()
        if ans not in ("n", "no"):
            return clip
    return paste_input(reader)


def paste_input(reader):
    print("\nPaste the whole footage section from Notion, then hit Enter.")
    print("(bolt will auto-detect when the paste is done)\n")
    lines = []
    # wait indefinitely for the first line, then 2s of silence = paste finished
    while True:
        line = reader.readline(timeout=None if not lines else 2.0)
        if line is None or line == "":
            if lines or line is None:
                break
            continue
        lines.append(line)
    return "".join(lines)


def _fmt_range(rng):
    def f(sec):
        m, s = divmod(sec, 60)
        h, m = divmod(m, 60)
        return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"
    return f"{f(rng[0])}-{f(rng[1])}"


def preview(sources, warnings):
    print("\n=== Parsed ===")
    for i, s in enumerate(sources, 1):
        rng = ", ".join(_fmt_range(r) for r in s.ranges) if s.ranges else "full video"
        print(f"{i}. {s.url}")
        print(f"   sections: {rng}")
        if s.notes:
            print(f"   notes: {s.notes}")
    for w in warnings:
        print(f"!  {w}")
    print()


def run_scripts(sources, cfg, ask=input):
    """`bolt script`: pull the transcript of every source into ingest."""
    from .transcript import fetch_script

    ingest = Path(cfg["ingest_dir"])
    tmp = ingest / ".bolt_tmp"
    tmp.mkdir(parents=True, exist_ok=True)

    ok, failed = 0, []
    for i, src in enumerate(sources, 1):
        print(f"\n--- [{i}/{len(sources)}] {src.url}")
        try:
            txt, srt, method = fetch_script(src, ingest, tmp, cfg)
            print(f"  -> {txt.name}  (via {method})")
            print(f"  -> {srt.name}")
            ok += 1
        except Exception as e:
            msg = str(e).splitlines()[0][:200]
            print(f"FAILED: {msg}")
            failed.append({"url": src.url, "error": msg})

    _cleanup_tmp(tmp)
    if ok:
        print(f"\nDone. {ok} script(s) in {ingest}")
    if failed:
        print(f"\n{len(failed)} source(s) failed:")
        for f in failed:
            print(f"  - {f['url']}\n    {f['error']}")
        return 1
    return 0


def _cleanup_tmp(tmp: Path):
    try:
        for leftover in tmp.iterdir():
            leftover.unlink(missing_ok=True)
        tmp.rmdir()
    except Exception:
        pass


def _login_tip(url: str, cfg):
    low = url.lower()
    if not cfg.get("cookies_browser") and ("instagram" in low or "tiktok" in low):
        site = "Instagram" if "instagram" in low else "TikTok"
        print(f"Tip: {site} often needs login cookies. Run `bolt config` and set your browser.")


def run(block_text, cfg, dry_run=False, ask=input, mode="download", with_script=False):
    sources, warnings = parse_block(block_text)
    preview(sources, warnings)
    if not sources:
        return 1
    if dry_run:
        print("(dry run, nothing downloaded)")
        return 0

    if mode == "script":
        ans = ask(f"Pull {len(sources)} script(s) to {cfg['ingest_dir']}? [Enter = yes, q = cancel]: ").strip().lower()
        if ans in ("q", "n", "no"):
            print("Cancelled.")
            return 0
        return run_scripts(sources, cfg, ask=ask)

    what = f"{len(sources)} source(s)" + (" + scripts" if with_script else "")
    ans = ask(f"Download {what} to {cfg['ingest_dir']}? [Enter = yes, q = cancel]: ").strip().lower()
    if ans in ("q", "n", "no"):
        print("Cancelled.")
        return 0

    from .downloader import download_source
    from .postprocess import make_premiere_ready
    from .manifest import write_manifest, ping_webhook

    ingest = Path(cfg["ingest_dir"])
    tmp = ingest / ".bolt_tmp"
    tmp.mkdir(parents=True, exist_ok=True)

    entries = []
    failed = []
    for i, src in enumerate(sources, 1):
        print(f"\n--- [{i}/{len(sources)}] {src.url}")
        try:
            downloads = download_source(src, ingest, tmp, cfg.get("cookies_browser", ""),
                                        handle_seconds=int(cfg.get("handle_seconds", 2)))
        except Exception as e:
            msg = str(e).splitlines()[0][:200]
            print(f"FAILED: {msg}")
            _login_tip(src.url, cfg)
            failed.append({"url": src.url, "error": msg})
            continue

        for d in downloads:
            final, action, vcodec, res = make_premiere_ready(d["path"], ingest, d["source_url"])
            size_mb = round(final.stat().st_size / 1_048_576, 1)
            rng = _fmt_range(d["range"]) if d["range"] else ""
            print(f"  -> {final.name}  ({res}, {vcodec}, {size_mb} MB, {action})")
            entries.append({
                "title": d["title"], "id": d["id"], "source_url": d["source_url"],
                "platform": d["extractor"], "range": rng, "notes": d["notes"],
                "file": final.name, "vcodec": vcodec, "resolution": res,
                "size_mb": size_mb, "action": action,
            })

    if with_script:
        from .transcript import fetch_script
        print("\n=== Scripts ===")
        for src in sources:
            try:
                txt, _, method = fetch_script(src, ingest, tmp, cfg)
                print(f"  -> {txt.name}  (via {method})")
            except Exception as e:
                print(f"  script failed for {src.url}: {str(e).splitlines()[0][:150]}")

    _cleanup_tmp(tmp)

    if entries:
        mpath, payload = write_manifest(ingest, entries)
        ping_webhook(cfg.get("webhook_url", ""), payload)
        print(f"\nDone. {len(entries)} clip(s) in {ingest}")
        print(f"Manifest: {mpath.name}")
    if failed:
        print(f"\n{len(failed)} source(s) failed:")
        for f in failed:
            print(f"  - {f['url']}\n    {f['error']}")
        return 1
    return 0


def main():
    ap = argparse.ArgumentParser(
        prog="bolt",
        description="Bolt Motivation footage ingest tool",
        epilog="Examples:  bolt  |  bolt <url> [<url>...]  |  bolt script [<url>...]  |  "
               "bolt block.txt  |  bolt config",
    )
    ap.add_argument("input", nargs="*",
                    help="'script' to pull transcripts, 'config', one or more links, "
                         "or a .txt file with the research block (default: paste mode)")
    ap.add_argument("--script", action="store_true",
                    help="also pull the transcript of every source after downloading")
    ap.add_argument("--dry-run", action="store_true", help="parse and preview only, no downloads")
    ap.add_argument("--no-update", action="store_true", help="skip update checks this run")
    ap.add_argument("--version", action="version", version=f"bolt {__version__}")
    args = ap.parse_args()

    cfg = cfg_mod.load()
    tokens = list(args.input)
    mode = "download"

    if tokens and tokens[0].lower() == "script":
        mode = "script"
        tokens = tokens[1:]

    if tokens and tokens[0].lower() == "config":
        cfg_mod.run_config_command(cfg)
        return 0

    print(f"bolt {__version__}")

    if not args.no_update and not args.dry_run:
        from .update import self_update, update_ytdlp
        self_update()
        update_ytdlp(cfg)

    if not cfg.get("ingest_dir") and not args.dry_run:
        cfg = cfg_mod.first_run_wizard(cfg)

    if tokens:
        # links pasted straight as arguments
        if all(URL_RE.search(t) for t in tokens):
            block = "\n".join(tokens)
            return run(block, cfg, dry_run=args.dry_run, mode=mode, with_script=args.script)
        # otherwise a .txt file with the research block
        p = Path(tokens[0])
        if not p.exists():
            print(f"Not a link and not a file: {tokens[0]}")
            return 1
        block = p.read_text(encoding="utf-8", errors="ignore")
        return run(block, cfg, dry_run=args.dry_run, mode=mode, with_script=args.script)

    reader = _StdinReader()
    block = clipboard_or_paste(reader)
    return run(block, cfg, dry_run=args.dry_run, ask=reader.ask, mode=mode, with_script=args.script)


if __name__ == "__main__":
    sys.exit(main())
