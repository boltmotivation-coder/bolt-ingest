"""Quick regression tests: python test_parser.py"""
import sys
from bolt_ingest.parser import parse_block, URL_RE

FAILED = []

def check(name, cond, extra=""):
    print(("ok   " if cond else "FAIL ") + name + (f"  ({extra})" if extra and not cond else ""))
    if not cond:
        FAILED.append(name)

# 1. Real Notion markdown paste, exactly like the broken PowerShell one
block = """**Source URL:** https://www.youtube.com/watch?v=lZkITuBp7pU
**`Timestamps (optional):** 00:00–00:00`
*Notes:*
**Source URL:** CBS Sunday Morning Norah and Dan
`Timestamps (optional): 00:00–00:00`
*Notes:*
Source URL: https://youtu.be/abc123XYZ
Timestamps (optional): 0:17-0:40, 1:20–1:35
Notes: banger clip
use the middle part
- https://www.tiktok.com/@guy/video/728
Source URL:
https://www.instagram.com/reel/Cxyz/
Upscale(s): 2:00-2:30
https://www.notion.so/bolt/research-page-123
"""
srcs, warns = parse_block(block)
urls = [s.url for s in srcs]
check("markdown Source URL picked up", "https://www.youtube.com/watch?v=lZkITuBp7pU" in urls, str(urls))
check("placeholder 00:00-00:00 (en dash) = full video", srcs[0].ranges == [])
check("embed-as-text warned, not crashed", any("CBS Sunday Morning" in w for w in warns), str(warns))
check("multi-range parsed", (17, 40) in srcs[1].ranges and (80, 95) in srcs[1].ranges, str(srcs[1].ranges))
check("multi-line notes", srcs[1].notes == "banger clip use the middle part", repr(srcs[1].notes))
check("bare tiktok link becomes a source", any("tiktok.com" in u for u in urls), str(urls))
check("url on line after 'Source URL:' label", any("instagram.com/reel" in u for u in urls), str(urls))
ig = [s for s in srcs if "instagram" in s.url][0]
check("Upscale(s) range attached", ig.ranges == [(120, 150)], str(ig.ranges))
check("notion.so link ignored", not any("notion" in u for u in urls), str(urls))

# 2. What argv joining produces when the first Notion line rides on `bolt `
argv_block = "**Source\nURL:**\nhttps://www.youtube.com/watch?v=lZkITuBp7pU"
srcs2, _ = parse_block(argv_block)
check("paste-on-same-line-as-bolt still yields the url",
      [s.url for s in srcs2] == ["https://www.youtube.com/watch?v=lZkITuBp7pU"], str([s.url for s in srcs2]))

# 3. Plain multiple links as args
srcs3, _ = parse_block("https://youtu.be/a1\nhttps://youtu.be/b2")
check("two plain links = two sources", len(srcs3) == 2)

# 4. URL glued to markdown junk
srcs4, _ = parse_block("Source URL: **https://youtu.be/xyz**")
check("bold-wrapped url cleaned", srcs4 and srcs4[0].url == "https://youtu.be/xyz", str([s.url for s in srcs4]))

# 5. Duplicate de-dupe
srcs5, w5 = parse_block("https://youtu.be/a1\nhttps://youtu.be/a1")
check("duplicates removed", len(srcs5) == 1 and any("Duplicate" in w for w in w5))

# 6. Garbage in, no crash, clear warning
srcs6, w6 = parse_block("Rules (for it to work)\n1. New Source button for every link.")
check("no urls -> empty + warning", srcs6 == [] and any("No source URLs" in w for w in w6))

# 7. Junk detector that guards interactive prompts
from bolt_ingest.parser import looks_like_template_junk
for junk in ["**`Timestamps (optional):** 00:00–00:00`", "*Notes:*",
             "**Source URL:** https://youtu.be/x", "0:17-0:40, 1:20-1:35"]:
    check(f"junk detected: {junk[:30]}", looks_like_template_junk(junk))
for ok in ["", "d", r"C:\Users\Admin\Documents\Working Folder\INGEST", "/Users/ed/clips"]:
    check(f"not junk: {ok or '(empty)'}", not looks_like_template_junk(ok))

print()
if FAILED:
    print(f"{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("all good")
