"""Parse and normalize EAEU certificate registration numbers."""

from __future__ import annotations

import re

from cert_parser.domain.errors import InvalidNumberError
from cert_parser.domain.models import CertificateNumber

SUPPORTED_COUNTRY_CODES = ("BY", "RU", "KZ", "AM", "KG")
_COUNTRY_GROUP = "|".join(SUPPORTED_COUNTRY_CODES)

# ЕАЭС BY/..., ЕАЭС Д BY/..., ТС BY/..., EAC RU C-...
_PREFIXED_COUNTRY_RE = re.compile(
    rf"(?:ЕАЭС|EAC|EAES|EADC|EAEC|EA3C|ТС|TC|CU)\s+(?:[A-ZА-ЯЁ]\s+)?({_COUNTRY_GROUP})\b",
    re.IGNORECASE,
)
_SLASH_COUNTRY_RE = re.compile(rf"\b({_COUNTRY_GROUP})\s*/", re.IGNORECASE)
_BARE_COUNTRY_RE = re.compile(
    rf"(?<![.\w])({_COUNTRY_GROUP})(?:\s*/|\s+(?=\d)|\.(?=\d)|(?:\s+[CС]\s*-))",
    re.IGNORECASE,
)
_KG_AGENCY_RE = re.compile(r"(?<![.\w])KG\d+/", re.IGNORECASE)
_LEADING_PREFIX_RE = re.compile(
    r"^(?:ЕАЭС|EAC|EAES|EADC|EAEC|EA3C|ТС|TC|CU)(?:\s+[A-ZА-ЯЁ])?\s+",
    re.IGNORECASE,
)
_NON_ALNUM_RE = re.compile(r"[^0-9A-ZА-ЯЁ]+", re.IGNORECASE)
_RU_CERT_MARK_RE = re.compile(r"(\bRU\s*)[CС](\s*-)", re.IGNORECASE)
_OCR_NUMERO_RE = re.compile(
    r"(?:[№]|(\bNg\b)|(\bNo\.?(?=\s))|(\bN(?=\s+(?:EA|ЕА))))\s*",
    re.IGNORECASE,
)
# EAEU prefix: OCR often mixes Latin/Cyrillic (EAЭC, EAEС, ЕAEC, …).
# No word boundaries — \b breaks on Cyrillic Э between Latin letters.
_OCR_EAEU_RE = re.compile(
    r"(?:"
    r"EAD[CС]|"
    r"[EЕ][AА][EЕЭ3З][CСS]"
    r")",
    re.IGNORECASE,
)
_OCR_TR_RE = re.compile(r"\bTP(?=\d)", re.IGNORECASE)
# EAC mark on scan often precedes country code instead of full «ЕАЭС» (EAC KZ …, EAC BY …).
_EAC_COUNTRY_RE = re.compile(
    rf"\bEAC\s+({_COUNTRY_GROUP})\b",
    re.IGNORECASE,
)
_UNION_PREFIX = r"(?:ЕАЭС|EAC|EAES|EADC|EAEC|EA3C|ТС|TC|CU)"
# Optional «Д» marks EAEU declarations (ЕАЭС Д BY/…); do not allow any single letter —
# OCR often leaves a stray «C» from mixed-script «EAЭC».
_CANDIDATE_RE = re.compile(
    rf"(?:{_UNION_PREFIX}\s+)?"
    r"(?:Д\s+)?"
    r"(?:"
    r"BY/[0-9A-ZА-ЯЁ.\-]+(?:\s+[0-9A-ZА-ЯЁ.\-/]*\d[0-9A-ZА-ЯЁ.\-/]*){0,6}"
    r"|RU[ \t]*[CС]\s*-[0-9A-ZА-ЯЁ.\-/]+"
    r"|KZ[ \t]+\d[0-9A-ZА-ЯЁ.\-]{8,40}"
    r"|AM[ \t]+[0-9A-ZА-ЯЁ.\-/]{8,40}"
    r"|KG[ \t]+[0-9A-ZА-ЯЁ.\-/]{8,40}"
    r"|KG\d+/[0-9A-ZА-ЯЁ.\-/]{6,60}"
    r")",
    re.IGNORECASE,
)


def collapse_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def fold_ocr_artifacts(value: str) -> str:
    """Fix typical RapidOCR confusions in EAEU registration numbers."""
    if not value:
        return ""
    folded = _OCR_NUMERO_RE.sub(" ", value)
    folded = _OCR_EAEU_RE.sub("ЕАЭС", folded)
    folded = _EAC_COUNTRY_RE.sub(r"ЕАЭС \1", folded)
    folded = _OCR_TR_RE.sub("ТР", folded)
    return folded


def compact_number(value: str) -> str:
    """Comparable form: letters/digits only, uppercased, RU C/С unified."""
    collapsed = collapse_whitespace(value).upper().replace("Ё", "Е")
    collapsed = _RU_CERT_MARK_RE.sub(r"\1С\2", collapsed)
    return _NON_ALNUM_RE.sub("", collapsed)


def parse_certificate_number(raw: str) -> CertificateNumber:
    if raw is None:
        raise InvalidNumberError("Номер сертификата не указан")

    normalized = collapse_whitespace(fold_ocr_artifacts(str(raw)))
    if not normalized:
        raise InvalidNumberError("Номер сертификата не указан")

    country_code = _extract_country_code(normalized)
    if country_code is None:
        raise InvalidNumberError(
            "Не удалось определить страну по номеру. "
            "Ожидается код BY, RU, KZ, AM или KG"
        )

    search_term = _LEADING_PREFIX_RE.sub("", normalized).strip() or normalized
    return CertificateNumber(
        raw=str(raw),
        normalized=normalized,
        compact=compact_number(normalized),
        country_code=country_code,
        search_term=search_term,
    )


def numbers_match(left: str, right: str) -> bool:
    compact_left = compact_number(left)
    compact_right = compact_number(right)
    if not compact_left or not compact_right:
        return False
    return compact_left == compact_right


def extract_certificate_candidates(text: str) -> list[str]:
    """Find unique registration-number candidates in free text or OCR output."""
    if not text:
        return []
    source = fold_ocr_artifacts(text)
    best: dict[tuple[str, str], str] = {}
    for match in _CANDIDATE_RE.finditer(source):
        candidate = collapse_whitespace(match.group(0)).strip(" .,;:()[]")
        try:
            parsed = parse_certificate_number(candidate)
        except InvalidNumberError:
            continue
        key = (parsed.country_code, compact_number(parsed.search_term))
        existing = best.get(key)
        if existing is None or _prefer_normalized(parsed.normalized, existing):
            best[key] = parsed.normalized
    return list(best.values())


def _prefer_normalized(left: str, right: str) -> bool:
    """Prefer ЕАЭС-prefixed form, then the longer normalized string."""
    left_eaeu = left.upper().startswith("ЕАЭС")
    right_eaeu = right.upper().startswith("ЕАЭС")
    if left_eaeu != right_eaeu:
        return left_eaeu
    return len(left) > len(right)


def _extract_country_code(normalized: str) -> str | None:
    prefixed = _PREFIXED_COUNTRY_RE.search(normalized)
    if prefixed:
        return prefixed.group(1).upper()
    if _KG_AGENCY_RE.search(normalized):
        return "KG"
    slashed = _SLASH_COUNTRY_RE.search(normalized)
    if slashed:
        return slashed.group(1).upper()
    bare = _BARE_COUNTRY_RE.search(normalized)
    if bare:
        return bare.group(1).upper()
    return None
