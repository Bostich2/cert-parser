"""Extract opendata and route config from EAEU bundle."""
from __future__ import annotations

import re

js = open("tests/fixtures/eaeu_main.js", encoding="utf-8").read()
for pat in [
    r"https://opendata[^\"']+",
    r"opendata[^\"']{0,120}",
    r"Qq=\[\{path:[^\]]{0,500}",
    r"registryList[^\"']{0,120}",
    r"conformityDocs[^\"']{0,120}",
    r"searchString[^\"']{0,80}",
    r"baseUrl[^\"']{0,120}",
    r"apiUrl[^\"']{0,120}",
]:
    hits = re.findall(pat, js)
    if hits:
        print(f"\n=== {pat[:40]} ({len(hits)}) ===")
        for h in hits[:15]:
            print(h[:220])
