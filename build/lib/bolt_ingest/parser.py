"""Parse a pasted Notion 'Sources & Footage' block into structured sources.

Matches the Bolt Motivation template:

    Source URL: https://...
    Timestamps (optional): 00:00-00:00
    Notes: whatever the researcher wrote

Rules honored:
- 00:00-00:00 (any dash type) = placeholder = full video
- Real ranges = download those sections only
- Multiple ranges: "0:17-0:40, 1:20-1:35"
- Editors may paste the whole section including the Rules text; the parser
  ignores anything that isn't attached to an actual Source URL.
"""

import re
from dataclasses import dataclass, field

# en dash / em dash / hyphen all accepted (Notion template uses an en dash)
_DASH = r"[-\u2013\u2014]"
_TIME = r"\d{1,2}(?::\d{1,2}){1,2}"  # M:SS, MM:SS, H:MM:SS
RANGE_RE = re.compile(rf"({_TIME})\s*{_DASH}\s*({_TIME})")
URL_RE = re.compile(r"https?://[^\s<>\"'\)\]]+")
_LIST_PREFIX = re.compile(r"^\s*(?:\d+[.)]|[-\u2022*>])\s*")


@dataclass
class Source:
    url: str = ""
    ranges: list = field(default_factory=list)  # list of (start_sec, end_sec)
    notes: str = ""


def ts_to_seconds(ts: str) -> int:
    parts = [int(p) for p in ts.split(":")]
    if len(parts) == 2:
        m, s = parts
        return m * 60 + s
    h, m, s = parts
    return h * 3600 + m * 60 + s


def seconds_to_tag(sec: int) -> str:
    m, s = divmod(sec, 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}{m:02d}{s:02d}"
    return f"{m:02d}{s:02d}"


def _extract_ranges(line: str):
    out = []
    for a, b in RANGE_RE.findall(line):
        start, end = ts_to_seconds(a), ts_to_seconds(b)
        if start == 0 and end == 0:
            continue  # 00:00-00:00 placeholder = full video
        if end <= start:
            continue  # garbage / typo, safer to grab full video than a broken cut
        out.append((start, end))
    return out


def parse_block(text: str):
    """Returns (sources, warnings)."""
    sources = []
    warnings = []
    current = None
    awaiting_url = False
    in_notes = False

    for raw in text.splitlines():
        line = _LIST_PREFIX.sub("", raw).strip()
        if not line:
            in_notes = False
            continue
        low = line.lower()
        urls = URL_RE.findall(line)

        # --- New source starts ---
        if low.startswith("source url"):
            if current is not None and current.url:
                sources.append(current)
            elif current is not None and not current.url:
                warnings.append("Found a 'Source URL:' block with no link in it. Skipped.")
            current = Source()
            in_notes = False
            if urls:
                current.url = urls[0]
                awaiting_url = False
            else:
                awaiting_url = True
            continue

        # URL on its own line (Notion sometimes wraps the link to the next line)
        if urls:
            if current is not None and awaiting_url:
                current.url = urls[0]
                awaiting_url = False
            else:
                # A bare link without the label: treat it as a new source anyway.
                if current is not None and current.url:
                    sources.append(current)
                current = Source(url=urls[0])
                in_notes = False
            # timestamps can share the line with the url
            if current is not None:
                current.ranges.extend(_extract_ranges(line.replace(current.url, "")))
            continue

        # --- Timestamps / upscale line ---
        if current is not None and ("timestamp" in low or low.startswith("upscale")):
            current.ranges.extend(_extract_ranges(line))
            in_notes = False
            continue

        # --- Notes ---
        if current is not None and low.startswith("notes"):
            note = line.split(":", 1)[1].strip() if ":" in line else ""
            current.notes = note
            in_notes = True
            continue

        # continuation of a multi-line note
        if current is not None and in_notes:
            current.notes = (current.notes + " " + line).strip()
            continue

        # a stray range line right under a source (label got lost in the paste)
        if current is not None and RANGE_RE.search(line) and len(line) < 60:
            current.ranges.extend(_extract_ranges(line))

    if current is not None:
        if current.url:
            sources.append(current)
        else:
            warnings.append("Last 'Source URL:' block had no link. Skipped.")

    if not sources:
        warnings.append("No source URLs found in what you pasted.")

    # de-dupe identical urls with identical ranges
    seen = set()
    unique = []
    for s in sources:
        key = (s.url, tuple(s.ranges))
        if key in seen:
            warnings.append(f"Duplicate source skipped: {s.url}")
            continue
        seen.add(key)
        unique.append(s)

    return unique, warnings
