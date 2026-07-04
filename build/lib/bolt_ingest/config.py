import json
import os
from pathlib import Path

CONFIG_DIR = Path.home() / ".bolt"
CONFIG_PATH = CONFIG_DIR / "config.json"

DEFAULTS = {
    "ingest_dir": "",
    "webhook_url": "",          # optional: Discord webhook for the manifest ping
    "cookies_browser": "",      # optional: "chrome" / "firefox" etc. Needed for Instagram.
    "handle_seconds": 2,        # extra seconds padded around each timestamp range (trim handles)
    "whisper_model": "small",   # faster-whisper model for `bolt script` fallback
    "last_ytdlp_update": 0,
}


def load():
    if CONFIG_PATH.exists():
        try:
            cfg = {**DEFAULTS, **json.loads(CONFIG_PATH.read_text())}
        except Exception:
            cfg = dict(DEFAULTS)
    else:
        cfg = dict(DEFAULTS)
    return cfg


def save(cfg):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2))


def first_run_wizard(cfg):
    print("\n== bolt first-time setup ==")
    print("Where is your ingest folder? (all downloads land here)")
    default = str(Path.home() / "ingest")
    path = input(f"Path [{default}]: ").strip().strip('"').strip("'") or default
    ingest = Path(os.path.expanduser(path)).resolve()
    ingest.mkdir(parents=True, exist_ok=True)
    cfg["ingest_dir"] = str(ingest)
    save(cfg)
    print(f"Saved. Downloads will go to: {ingest}")
    print("(Change anytime with: bolt config)\n")
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
        p = input("New ingest folder path: ").strip().strip('"').strip("'")
        if p:
            ingest = Path(os.path.expanduser(p)).resolve()
            ingest.mkdir(parents=True, exist_ok=True)
            cfg["ingest_dir"] = str(ingest)
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
