import json
import os
import re
from pathlib import Path

CONFIG_DIR = Path.home() / ".bolt"
CONFIG_PATH = CONFIG_DIR / "config.json"


def _clean_path(raw: str) -> str:
    """Tidy a pasted/typed/dragged folder path.

    Handles surrounding quotes and, on macOS/Linux, the backslash-escaped
    spaces you get when you drag a folder into the Terminal.
    """
    s = raw.strip().strip('"').strip("'").strip()
    if os.name != "nt":  # don't touch Windows path separators
        s = re.sub(r"\\([ ()&'\"])", r"\1", s)
    return s

DEFAULTS = {
    "ingest_dir": "",
    "webhook_url": "",          # optional: Discord webhook for the manifest ping
    "cookies_browser": "",      # optional: "chrome" / "firefox" etc. Needed for Instagram.
    "handle_seconds": 2,        # extra seconds padded around each timestamp range (trim handles)
    "whisper_model": "small",   # faster-whisper model for `bolt script` fallback
    "last_ytdlp_update": 0,
}


# folders we never descend into while hunting for an ingest folder
_SKIP_DIRS = {"library", "node_modules", "applications", "venv", ".venv",
              "site-packages", "__pycache__", "photos library.photoslibrary"}


def _subdirs(path: Path):
    """Direct child directories of `path`, skipping hidden/heavy ones. Never raises."""
    out = []
    try:
        with os.scandir(path) as it:
            for e in it:
                name = e.name
                if name.startswith(".") or name.lower() in _SKIP_DIRS:
                    continue
                try:
                    if e.is_dir(follow_symlinks=False):
                        out.append(Path(e.path))
                except OSError:
                    continue
    except OSError:
        pass
    return out


def _ci_child(parent: Path, name: str):
    """Child dir of `parent` matching `name` case-insensitively, or None."""
    low = name.lower()
    for d in _subdirs(parent):
        if d.name.lower() == low:
            return d
    return None


def recommended_paths():
    """The canonical layout bolt recommends: Documents/Working Folder/{INGEST,PROJECTS}.

    Reuses existing 'Documents' / 'Working Folder' dirs by whatever case they
    already have, so we never make a duplicate next to one that exists.
    Returns (working_folder, ingest, projects) as Paths (may not exist yet).
    """
    home = Path.home()
    docs = _ci_child(home, "Documents") or (home / "Documents")
    wf = _ci_child(docs, "Working Folder") or (docs / "Working Folder")
    ingest = _ci_child(wf, "INGEST") or (wf / "INGEST")
    projects = _ci_child(wf, "PROJECTS") or (wf / "PROJECTS")
    return wf, ingest, projects


def find_ingest_dir():
    """Auto-locate the ingest folder, preferring bolt's canonical layout.

    1. Documents/Working Folder/INGEST (the recommended structure) always wins.
    2. Otherwise a breadth-first hunt for any folder named 'ingest' in the usual
       roots, stopping at the shallowest match so it never crawls deep project
       trees. Returns a Path or None.
    """
    home = Path.home()

    # 1. canonical layout
    _, canonical_ingest, _ = recommended_paths()
    if canonical_ingest.exists():
        return canonical_ingest

    def best(hits):
        hits = list(dict.fromkeys(hits))
        # prefer anything living under a "Working Folder", then shallower paths
        hits.sort(key=lambda p: (
            0 if any(part.lower() == "working folder" for part in p.parts) else 1,
            len(p.parts),
            0 if "Documents" in p.parts else 1,
        ))
        return hits[0]

    # a bare ~/ingest
    top = [d for d in _subdirs(home) if d.name.lower() == "ingest"]
    if top:
        return best(top)

    roots = [home / "Documents", home / "Desktop", home / "Downloads", home / "Movies"]
    frontier = [r for r in roots if r.exists()]
    for _ in range(4):  # depth cap
        level_hits, next_frontier = [], []
        for d in frontier:
            for child in _subdirs(d):
                if child.name.lower() == "ingest":
                    level_hits.append(child)
                else:
                    next_frontier.append(child)
        if level_hits:
            return best(level_hits)
        frontier = next_frontier
    return None


def load():
    if CONFIG_PATH.exists():
        try:
            cfg = {**DEFAULTS, **json.loads(CONFIG_PATH.read_text(encoding="utf-8"))}
        except Exception:
            cfg = dict(DEFAULTS)
    else:
        cfg = dict(DEFAULTS)
    return cfg


def save(cfg):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2), encoding="utf-8")


def _ask_path(prompt: str) -> str:
    """input() that shrugs off leftover research-block lines still queued in the
    console after a botched paste (they'd otherwise become 'folder paths')."""
    from .parser import looks_like_template_junk
    ans = input(prompt)
    if ans.strip() and looks_like_template_junk(ans):
        print("(that looks like leftover pasted text, not a folder - using the default)")
        return ""
    return _clean_path(ans)


def _make_dir(candidate: str, fallback: Path) -> Path:
    """Resolve + create the chosen folder; on any bad path, fall back safely
    instead of crashing (Windows raises on characters like * : ` in paths)."""
    try:
        p = Path(os.path.expanduser(candidate)).resolve() if candidate else fallback
        p.mkdir(parents=True, exist_ok=True)
        return p
    except (OSError, ValueError):
        print(f"Couldn't use \"{candidate[:60]}\" as a folder - using {fallback} instead.")
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback


def first_run_wizard(cfg):
    print("\n== bolt first-time setup ==")
    print("Where should bolt save your downloads?\n")
    found = find_ingest_dir()

    if found:
        print(f"Found a folder that looks right:  {found}\n")
        ans = _ask_path("Use it? [Enter = yes / or type/paste/drag another folder]: ")
        ingest = _make_dir(ans, found)
    else:
        wf, ingest_rec, projects_rec = recommended_paths()
        downloads = Path.home() / "Downloads"
        print("Pick one — or just type, paste, or drag any folder you want:\n")
        print(f"  [Enter]   Recommended editor layout   {wf}")
        print( "                                        (makes INGEST/ for footage + PROJECTS/ for edits)")
        print(f"  d         Just use my Downloads        {downloads}")
        print( "  <folder>  Any path you type/paste/drag\n")
        ans = _ask_path("Your choice: ")
        if not ans:
            try:
                projects_rec.mkdir(parents=True, exist_ok=True)
                print(f"Created {wf} with INGEST/ and PROJECTS/.")
            except OSError:
                pass
            ingest = _make_dir("", ingest_rec)
        elif ans.lower() == "d":
            ingest = _make_dir("", downloads)
        else:
            ingest = _make_dir(ans, ingest_rec)

    cfg["ingest_dir"] = str(ingest)
    save(cfg)
    print(f"\nSaved. Downloads will go to: {ingest}")
    print("Change this anytime with:  bolt config\n")
    return cfg


def run_config_command(cfg):
    print("\n== bolt config ==")
    print(f"1. Ingest folder      : {cfg['ingest_dir'] or '(not set)'}")
    print(f"2. Webhook URL        : {cfg['webhook_url'] or '(off)'}")
    print(f"3. Cookies browser    : {cfg['cookies_browser'] or '(off, needed for Instagram)'}")
    print(f"4. Trim handles (sec) : {cfg.get('handle_seconds', 2)}")
    print(f"5. Whisper model      : {cfg.get('whisper_model', 'small')} (tiny/base/small/medium/large-v3)")
    choice = input("Change which? (1-5, Enter to exit): ").strip()
    if choice == "1":
        p = _ask_path("New download folder (type, paste, or drag it here): ")
        if p:
            ingest = _make_dir(p, Path(cfg["ingest_dir"]) if cfg["ingest_dir"] else Path.home() / "Downloads")
            cfg["ingest_dir"] = str(ingest)
            print(f"Downloads will now go to: {ingest}")
    elif choice == "2":
        cfg["webhook_url"] = input("Webhook URL (blank to disable): ").strip()
    elif choice == "3":
        cfg["cookies_browser"] = input(
            "Browser to pull cookies from (chrome/firefox/edge/safari/brave, blank to disable): "
        ).strip().lower()
    elif choice == "4":
        v = input("Seconds of handle padding around each timestamp range [2]: ").strip()
        if v.isdigit():
            cfg["handle_seconds"] = int(v)
    elif choice == "5":
        v = input("Whisper model (tiny/base/small/medium/large-v3) [small]: ").strip().lower()
        if v:
            cfg["whisper_model"] = v
    save(cfg)
    print("Saved.")
