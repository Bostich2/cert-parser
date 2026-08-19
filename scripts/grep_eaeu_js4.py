"""List all URLs and env-like config from EAEU bundle."""
from __future__ import annotations

import re

js = open("tests/fixtures/eaeu_main.js", encoding="utf-8").read()
print("all https urls:")
for u in sorted(set(re.findall(r"https://[a-zA-Z0-9._/-]+", js))):
    print(" ", u)
print("\nstrings with api:")
for s in sorted(set(re.findall(r'"[^"]*api[^"]*"', js, re.I))):
    if len(s) < 120:
        print(s)
print("\nstrings with search endpoint:")
for s in sorted(set(re.findall(r'"[^"]*search[^"]*"', js, re.I))):
    if "/" in s and len(s) < 120:
        print(s)
