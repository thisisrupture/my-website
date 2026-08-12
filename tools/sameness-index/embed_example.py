"""
Embed worked_example.json into index.html.

The browser blocks fetch() on file:// URLs, so a double-clicked index.html
cannot read the JSON sitting next to it. Embedding it means the worked example
opens with no server and no network. Run after generate_worked_example.py.

Run: python3 embed_example.py
"""

import re

HTML = "index.html"
JSON_FILE = "worked_example.json"
OPEN_TAG = '<script type="application/json" id="worked-example">'
MARKER = "</body>"

html = open(HTML).read()
data = open(JSON_FILE).read()

if "</script" in data.lower():
    raise SystemExit("Refusing to embed: the JSON contains a closing script tag.")

block = f"{OPEN_TAG}\n{data}\n</script>\n"

if OPEN_TAG in html:
    html = re.sub(
        re.escape(OPEN_TAG) + r".*?</script>\s*",
        lambda _: block,
        html,
        count=1,
        flags=re.S,
    )
    action = "replaced"
else:
    if MARKER not in html:
        raise SystemExit("Could not find the insertion point in index.html.")
    html = html.replace(MARKER, block + "\n" + MARKER, 1)
    action = "inserted"

open(HTML, "w").write(html)
print(f"{action} {len(data):,} bytes of worked example into {HTML} ({len(html):,} bytes total)")
