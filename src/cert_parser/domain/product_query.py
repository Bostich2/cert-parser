from __future__ import annotations

import re

from cert_parser.domain.certificate_number import collapse_whitespace
from cert_parser.domain.models import ProductSearchQuery

MIN_QUERY_LENGTH = 4
MIN_TOKEN_LENGTH = 3
MIN_STEM_SOURCE_LENGTH = 5
MIN_STEM_LENGTH = 4
MAX_AND_TOKENS = 2
PHRASE_MAX_TOKENS = 2
PHRASE_MAX_CHARS = 32

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


def registry_search_steps(query: ProductSearchQuery) -> list[tuple[tuple[str, ...], str]]:
    """Needles for registry contains/LIKE. Skip unique full-title phrase scans."""
    steps: list[tuple[tuple[str, ...], str]] = []
    use_phrase = _use_phrase_step(query)
    if use_phrase:
        steps.append(((query.normalized,), "phrase"))
    significant = significant_tokens(query.tokens)
    if significant:
        steps.append((significant, "tokens"))
    if use_phrase:
        stems = tuple(stem for token in significant if (stem := _stem(token)))
        if stems:
            steps.append((stems, "stems"))
    if not steps and query.normalized:
        steps.append(((query.normalized,), "phrase"))
    return steps


def significant_tokens(tokens: tuple[str, ...]) -> tuple[str, ...]:
    """Keep letter-bearing tokens; drop sizes like 235 / 65. Cap AND width."""
    filtered = [token for token in tokens if any(ch.isalpha() for ch in token)]
    return tuple(filtered[:MAX_AND_TOKENS])


def contiguous_search_terms(query: ProductSearchQuery) -> list[str]:
    """Single contains-strings for APIs that cannot AND separate tokens."""
    terms: list[str] = []
    if _use_phrase_step(query) and query.normalized:
        terms.append(query.normalized)
    significant = significant_tokens(query.tokens)
    if len(significant) >= 2:
        pair = " ".join(significant[:2])
        if pair not in terms:
            terms.append(pair)
    if significant and significant[0] not in terms:
        terms.append(significant[0])
    if not terms and query.normalized:
        terms.append(query.normalized)
    return terms


def _use_phrase_step(query: ProductSearchQuery) -> bool:
    return (
        len(query.tokens) <= PHRASE_MAX_TOKENS
        and len(query.normalized) <= PHRASE_MAX_CHARS
    )


def _stem(token: str) -> str | None:
    if len(token) < MIN_STEM_SOURCE_LENGTH:
        return None
    drop = 2 if len(token) >= 6 else 1
    stem = token[:-drop]
    if len(stem) < MIN_STEM_LENGTH:
        stem = token[:MIN_STEM_LENGTH]
    return stem
