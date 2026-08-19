"""Find collection names for register 35 in EAEU bundle/config."""
from __future__ import annotations

import json
import re

config = json.load(open("tests/fixtures/eaeu_config.json", encoding="utf-8"))
js = open("tests/fixtures/eaeu_main.js", encoding="utf-8").read()

print("config keys", config.get("registers", {}).keys())
for key, val in config.get("registers", {}).items():
    if isinstance(val, dict) and "search" in str(val):
        searches = re.findall(r'"search"\s*:\s*"([^"]+)"', json.dumps(val))
        if searches:
            print(key, searches[:5])

hits = sorted(set(re.findall(r"kbdread\.service-prop-35[^\"']+", js)))
print("\njs 35 collections", len(hits))
for h in hits[:30]:
    print(h)

hits2 = sorted(set(re.findall(r"kbdread\.[^\"']+", js)))
print("\nall kbdread in js", len(hits2))
for h in hits2:
    if "35" in h or "conformityDoc" in h.lower() or "conformitydoc" in h.lower():
        print(h)
