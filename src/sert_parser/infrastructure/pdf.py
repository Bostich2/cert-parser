from __future__ import annotations

import logging
from functools import lru_cache

from sert_parser.config import Settings
from sert_parser.domain.certificate_number import (
    collapse_whitespace,
    extract_certificate_candidates,
)
from sert_parser.domain.errors import PdfReadError
from sert_parser.logging_setup import log_step

logger = logging.getLogger(__name__)

_HEADER_RATIO = 0.32
_HEADER_DPI = 320
_PAGE_DPI = 220


def extract_numbers_from_pdf(payload: bytes, settings: Settings) -> list[str]:
    if not payload:
        raise PdfReadError("Файл PDF пустой")
    if len(payload) > settings.pdf_max_bytes:
        max_mb = settings.pdf_max_bytes // (1024 * 1024)
        raise PdfReadError(f"PDF больше {max_mb} МБ")
    log_step(f"PDF: размер {len(payload)} байт")
    try:
        import fitz
    except ImportError as exc:
        raise PdfReadError("Не установлен модуль pymupdf") from exc
    try:
        document = fitz.open(stream=payload, filetype="pdf")
    except Exception as exc:
        raise PdfReadError("Не удалось открыть PDF") from exc
    try:
        text = _extract_text(document)
        numbers = extract_certificate_candidates(text)
        log_step(f"PDF: текстовый слой, страниц {document.page_count}, номеров {len(numbers)}")
        if numbers:
            log_step("PDF: " + ", ".join(numbers[:8]))
            return numbers
        if not settings.pdf_ocr_enabled:
            log_step("PDF: OCR выключен, поиск по картинкам пропущен")
            return []
        langs = _ocr_lang_sequence(settings.pdf_ocr_rec_lang)
        log_step(
            f"PDF: в тексте пусто, запускаю OCR (сначала 1-я стр., "
            f"при необходимости до {settings.pdf_ocr_max_pages} стр.) "
            f"язык {', '.join(langs)}"
        )
        ocr_text = _ocr_text(document, settings.pdf_ocr_max_pages, langs)
        ocr_numbers = extract_certificate_candidates(ocr_text)
        log_step(f"PDF: OCR, номеров {len(ocr_numbers)}")
        if ocr_numbers:
            log_step("PDF: " + ", ".join(ocr_numbers[:8]))
        elif ocr_text:
            log_step(f"PDF: OCR текст без номера: {_preview(ocr_text)}")
        return ocr_numbers
    finally:
        document.close()


def _extract_text(document) -> str:
    chunks: list[str] = []
    for page in document:
        chunks.append(page.get_text("text") or "")
    return "\n".join(chunks)


def _ocr_lang_sequence(primary: str) -> tuple[str, ...]:
    lang = (primary or "eslav").strip().lower()
    if lang in {"eslav", "cyrillic"}:
        return (lang, "latin")
    return (lang,)


def _ocr_text(document, max_pages: int, langs: tuple[str, ...]) -> str:
    page_limit = min(max_pages, document.page_count)
    chunks: list[str] = []
    if _ocr_page(document, 0, page_limit, langs, chunks):
        return "\n".join(chunks)
    if page_limit <= 1:
        return "\n".join(chunks)
    log_step("PDF: на первой странице номер не найден, пробую следующие")
    for index in range(1, page_limit):
        if _ocr_page(document, index, page_limit, langs, chunks):
            break
    return "\n".join(chunks)


def _ocr_page(
    document,
    index: int,
    page_count: int,
    langs: tuple[str, ...],
    chunks: list[str],
) -> bool:
    """OCR header then full page. Returns True when a certificate number is found."""
    page = document.load_page(index)
    rect = page.rect
    header_clip = (
        rect.x0,
        rect.y0,
        rect.x1,
        rect.y0 + rect.height * _HEADER_RATIO,
    )
    log_step(f"PDF: страница {index + 1} из {page_count}, распознаю шапку")
    header_png = page.get_pixmap(dpi=_HEADER_DPI, clip=header_clip).tobytes("png")
    header_text = _ocr_image_langs(header_png, langs, f"шапка стр. {index + 1}")
    if header_text:
        chunks.append(header_text)
        if extract_certificate_candidates("\n".join(chunks)):
            return True
    log_step(f"PDF: страница {index + 1} из {page_count}, распознаю лист целиком")
    page_png = page.get_pixmap(dpi=_PAGE_DPI).tobytes("png")
    page_text = _ocr_image_langs(page_png, langs, f"стр. {index + 1}")
    if page_text:
        chunks.append(page_text)
        if extract_certificate_candidates("\n".join(chunks)):
            return True
    return False


def _ocr_image_langs(image_bytes: bytes, langs: tuple[str, ...], label: str) -> str:
    combined: list[str] = []
    for lang in langs:
        engine = _ocr_engine(lang)
        if engine is None:
            log_step(f"PDF: OCR [{lang}] не запустился")
            continue
        log_step(f"PDF: OCR {label} [{lang}]…")
        text = _ocr_image(engine, image_bytes)
        if not text:
            log_step(f"PDF: OCR {label} [{lang}] — пусто")
            continue
        log_step(f"PDF: OCR {label} [{lang}]: {_preview(text)}")
        combined.append(text)
        if extract_certificate_candidates("\n".join(combined)):
            return "\n".join(combined)
    return "\n".join(combined)


def _ocr_image(engine, image_bytes: bytes) -> str:
    try:
        raw = engine(image_bytes)
    except Exception:
        logger.exception("OCR failed on image")
        return ""
    return _texts_from_ocr_result(raw)


def _preview(text: str, limit: int = 180) -> str:
    collapsed = collapse_whitespace(text)
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[:limit] + "…"


def _texts_from_ocr_result(raw: object) -> str:
    txts = getattr(raw, "txts", None)
    if txts:
        return " ".join(str(item) for item in txts if item)
    if isinstance(raw, tuple) and raw:
        rows = raw[0]
        if rows:
            return " ".join(str(item[1]) for item in rows if len(item) > 1)
    if isinstance(raw, list) and raw:
        return " ".join(str(item[1]) for item in raw if len(item) > 1)
    return ""


def reset_ocr_engines() -> None:
    _ocr_engine.cache_clear()


@lru_cache(maxsize=8)
def _ocr_engine(lang: str):
    RapidOCR = _import_rapidocr()
    if RapidOCR is None:
        return None
    try:
        if lang == "ch":
            return RapidOCR()
        from rapidocr import LangRec, ModelType, OCRVersion

        return RapidOCR(
            params={
                "Rec.lang_type": LangRec(lang),
                "Rec.ocr_version": OCRVersion.PPOCRV5,
                "Rec.model_type": ModelType.MOBILE,
            }
        )
    except Exception as exc:
        logger.exception("Failed to initialize RapidOCR lang=%s", lang)
        log_step(f"PDF: OCR [{lang}] ошибка запуска: {exc}")
        return None


def _import_rapidocr():
    try:
        from rapidocr import RapidOCR
    except ImportError:
        try:
            from rapidocr_onnxruntime import RapidOCR
        except ImportError:
            logger.exception(
                "RapidOCR is not installed. Run: pip install rapidocr onnxruntime"
            )
            return None
    return RapidOCR
