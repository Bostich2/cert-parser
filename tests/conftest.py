import os

# Stable semver for tests and local runs without git tags.
os.environ.setdefault("SERT_PARSER_VERSION", "0.2.0")
