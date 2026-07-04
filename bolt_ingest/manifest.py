import getpass
import json
import platform
import time
import urllib.request
from pathlib import Path


def write_manifest(ingest_dir: Path, entries):
    mdir = ingest_dir / "_manifests"
    mdir.mkdir(exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    payload = {
        "editor": getpass.getuser(),
        "machine": platform.node(),
        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "clips": entries,
    }
    path = mdir / f"bolt_{stamp}.json"
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
    return path, payload


def ping_webhook(url: str, payload):
    if not url:
        return
    lines = [f"**bolt** — {payload['editor']} on {payload['machine']} pulled {len(payload['clips'])} clip(s):"]
    for c in payload["clips"]:
        rng = f" [{c['range']}]" if c.get("range") else ""
        lines.append(f"- {c['title']}{rng} — {c['resolution']} {c['vcodec']} ({c['action']})")
    text = "\n".join(lines)[:1900]

    if "discord.com/api/webhooks" in url:
        body = json.dumps({"content": text}).encode()
    else:
        body = json.dumps(payload).encode()
    try:
        req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=8)
    except Exception:
        print("(webhook ping failed, manifest still saved locally)")
