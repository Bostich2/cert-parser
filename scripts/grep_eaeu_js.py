"""Extract API paths from EAEU main JS bundle."""
from __future__ import annotations

import re

import httpx

URL = "https://tech.eaeunion.org/tech/main.ed9d56ee7650e4ef.js"
OUT = "tests/fixtures/eaeu_main.js"


def main() -> None:
    js = httpx.get(URL, timeout=60, headers={"User-Agent": "Mozilla/5.0"}).text
    open(OUT, "w", encoding="utf-8").write(js)
    print("saved", len(js))
    apis = sorted(
        {
            h
            for h in re.findall(r"/tech/[A-Za-z0-9_./-]{5,120}", js)
            if any(x in h.lower() for x in ("api", "search", "registry", "conformity", "filter", "list", "gateway"))
        }
    )
    print("api paths", len(apis))
    for h in apis[:50]:
        print(h)
    for needle in ["conformityDocs", "registryList", "DocNumber", "registrationNumber", "searchText"]:
        idx = js.find(needle)
        print(f"\n{needle} first at {idx}")
        if idx >= 0:
            print(js[max(0, idx - 80) : idx + 120].replace("\n", " ")[:200])


if __name__ == "__main__":
    main()
