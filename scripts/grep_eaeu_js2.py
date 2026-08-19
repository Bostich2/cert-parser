"""Search minified EAEU bundle for endpoint strings."""
from __future__ import annotations

import re

js = open("tests/fixtures/eaeu_main.js", encoding="utf-8").read()
needles = [
    "conformity",
    "registry",
    "register",
    "35-1",
    "35_1",
    "search",
    "gateway",
    "docNumber",
    "DocId",
    "validity",
    "statusCode",
    "country",
    "AM ",
    "eaeunion",
]
for needle in needles:
    count = js.lower().count(needle.lower())
    if count:
        print(needle, count)
        idx = js.lower().find(needle.lower())
        print(" ", js[max(0, idx - 60) : idx + len(needle) + 80].replace("\n", " ")[:180])

# extract quoted strings containing tech or register
strings = re.findall(r'"([^"]{5,120})"', js)
interesting = [
    s
    for s in strings
    if any(x in s.lower() for x in ("tech/", "register", "conform", "search", "gateway", "api/", "35"))
]
print("\ninteresting strings", len(interesting))
for s in sorted(set(interesting))[:80]:
    print(s)
