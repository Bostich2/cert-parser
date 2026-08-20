from __future__ import annotations

import re

from cert_parser.domain.certificate_number import collapse_whitespace
from cert_parser.domain.models import ProductSearchQuery

MIN_QUERY_LENGTH = 4
MIN_TOKEN_LENGTH = 3
MIN_STEM_SOURCE_LENGTH = 5
MIN_STEM_LENGTH = 4

_PUNCT_RE = re.compile(r"""['"`«»„“”()\[\]{}.,;:!?/\\|+\-*=#@~^$%&]+""")


def parse_product_search_query(raw: str | None) -> ProductSearchQuery | None:
    original = "" if raw is None else str(raw)
    trimmed = collapse_whitespace(original)
    if len(trimmed) < MIN_QUERY_LENGTH:
        return None
    folded = trimmed.replace("ё", "е").replace("Ё", "Е")
    normalized = collapse_whitespace(_PUNCT_RE.sub(" ", folded))
    if not normalized:
        return None
    tokens = tuple(part for part in normalized.split(" ") if len(part) >= MIN_TOKEN_LENGTH)
    stems = tuple(stem for token in tokens if (stem := _stem(token)))
    return ProductSearchQuery(
        raw=original,
        normalized=normalized,
        tokens=tokens,
        stems=stems,
    )


def _stem(token: str) -> str | None:
    if len(token) < MIN_STEM_SOURCE_LENGTH:
        return None
    drop = 2 if len(token) >= 6 else 1
    stem = token[:-drop]
    if len(stem) < MIN_STEM_LENGTH:
        stem = token[:MIN_STEM_LENGTH]
    return stem
