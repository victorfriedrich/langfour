"""The one place the API decides what a language is.

The internal key is the ISO 639-1 code, matching `words.language` and every
RPC argument. English long names ('spanish') are a display concern and a
legacy input format; they are accepted at the boundary and converted here,
never passed further in.

This replaces six ad-hoc mapping tables that had drifted apart -- two of them
silently missing French, which is how a French learner ended up being served
Spanish words.
"""

from __future__ import annotations

# code -> English display name
LANGUAGES: dict[str, str] = {
    "es": "Spanish",
    "de": "German",
    "it": "Italian",
    "fr": "French",
}

SUPPORTED_CODES: tuple[str, ...] = tuple(LANGUAGES)

_BY_NAME = {name.lower(): code for code, name in LANGUAGES.items()}


def to_code(language: str | None) -> str | None:
    """Return the ISO code for a code or an English name, else None.

    None rather than a fallback: a bad value should produce an empty result,
    not silently the wrong language. The previous `default: 'spanish'` in the
    extension is exactly the bug this avoids.
    """
    if not language:
        return None
    normalized = language.strip().lower()
    if normalized in LANGUAGES:
        return normalized
    return _BY_NAME.get(normalized)


def require_code(language: str | None) -> str:
    """to_code(), raising on anything unrecognised."""
    code = to_code(language)
    if code is None:
        raise ValueError(
            f"Unsupported language: {language!r}. Expected one of {', '.join(SUPPORTED_CODES)}."
        )
    return code


def display_name(language: str | None) -> str | None:
    """Human-readable name, for UI and log lines only."""
    code = to_code(language)
    return LANGUAGES[code] if code else None
