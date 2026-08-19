from sert_parser.version import get_version

__all__ = ["__version__", "get_version"]


def __getattr__(name: str) -> str:
    if name == "__version__":
        return get_version()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
