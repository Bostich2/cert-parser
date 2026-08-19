class CertParserError(Exception):
    """Base domain error."""

    error_code = "error"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class InvalidNumberError(CertParserError):
    error_code = "invalid_number"


class UnsupportedCountryError(CertParserError):
    error_code = "unsupported_country"

    def __init__(self, country_code: str) -> None:
        self.country_code = country_code
        super().__init__(f"Страна {country_code} пока не поддерживается")


class CertificateNotFoundError(CertParserError):
    error_code = "not_found"

    def __init__(self, number: str) -> None:
        super().__init__(f"Сертификат «{number}» не найден в реестре")


class SourceUnavailableError(CertParserError):
    error_code = "source_unavailable"

    def __init__(self, message: str = "Реестр недоступен") -> None:
        super().__init__(message)


class NoNumbersInPdfError(CertParserError):
    error_code = "no_numbers_in_pdf"

    def __init__(self, message: str = "В PDF не найден номер сертификата") -> None:
        super().__init__(message)


class PdfReadError(CertParserError):
    error_code = "invalid_pdf"

    def __init__(self, message: str = "Не удалось прочитать PDF") -> None:
        super().__init__(message)


class XlsxReadError(CertParserError):
    error_code = "invalid_xlsx"

    def __init__(self, message: str = "Не удалось прочитать Excel") -> None:
        super().__init__(message)


class AmbiguousMatchError(CertParserError):
    error_code = "ambiguous"

    def __init__(self, number: str) -> None:
        super().__init__(
            f"По номеру «{number}» найдено несколько сертификатов. Укажите номер целиком"
        )
