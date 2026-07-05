import os
import re
import subprocess
import sys
import time
import urllib.request

from . import REPO, __version__
from . import config as cfg_mod

RAW_VERSION_URL = f"https://raw.githubusercontent.com/{REPO}/main/bolt_ingest/__init__.py"
GIT_URL = f"git+https://github.com/{REPO}.git"


def _remote_version():
    try:
        with urllib.request.urlopen(RAW_VERSION_URL, timeout=4) as r:
            text = r.read().decode("utf-8", "ignore")
        m = re.search(r'__version__\s*=\s*"([^"]+)"', text)
        return m.group(1) if m else None
    except Exception:
        return None


def _ver_tuple(v):
    return tuple(int(x) for x in re.findall(r"\d+", v)[:3] or [0])


def self_update():
    """Check GitHub for a newer bolt version; upgrade and restart if found."""
    if os.environ.get("BOLT_UPDATED") or "CHANGE-ME" in REPO:
        return
    remote = _remote_version()
    if not remote or _ver_tuple(remote) <= _ver_tuple(__version__):
        return
    print(f"New bolt version available — updating {__version__} -> {remote} (takes ~30s, one-off)...")
    cmds = [
        ["pipx", "upgrade", "bolt-ingest"],
        ["pipx", "install", "--force", GIT_URL],
        [sys.executable, "-m", "pip", "install", "-q", "--upgrade", GIT_URL],
    ]
    for cmd in cmds:
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
            if r.returncode == 0:
                print("Updated. Restarting...")
                env = dict(os.environ, BOLT_UPDATED="1")
                os.execvpe(sys.argv[0], sys.argv, env)
        except FileNotFoundError:
            continue
        except Exception:
            break
    print("Auto-update failed (not a big deal), continuing with current version.")


def update_ytdlp(cfg):
    """Keep yt-dlp fresh. YouTube breaks it constantly; this absorbs that. Runs max once per day."""
    now = time.time()
    if now - cfg.get("last_ytdlp_update", 0) < 86400:
        return
    print("Keeping yt-dlp fresh (daily check, a few seconds)...")
    try:
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "-q", "--upgrade", "yt-dlp"],
            capture_output=True, timeout=300,
        )
    except Exception:
        pass
    cfg["last_ytdlp_update"] = now
    cfg_mod.save(cfg)
