"""Small Unicode-aware text helpers shared by speech analytics, question
de-duplication, prompt building and transcription.

Why this exists: the original tokenizers used ``[a-zA-Z']+``. That matches no
characters at all in Devanagari (Hindi/Marathi), Tamil, Arabic, CJK, etc., so
every non-English answer measured as "0 words" and every non-English question
looked unique. Python's ``\\w`` is also not enough: it does not match combining
vowel signs (Unicode categories Mn/Mc), so it would split Devanagari words in
the middle.
"""

import re
import unicodedata

_APOSTROPHES = {"'", "\u2019"}

# ISO-639-1 codes for the language names the UI offers (and common endonyms).
# Used for the transcription language hint and for choosing filler vocabulary.
_LANGUAGE_CODES: dict[str, str] = {
    "english": "en",
    "hindi": "hi",
    "हिन्दी": "hi",
    "हिंदी": "hi",
    "marathi": "mr",
    "मराठी": "mr",
    "tamil": "ta",
    "telugu": "te",
    "kannada": "kn",
    "malayalam": "ml",
    "bengali": "bn",
    "gujarati": "gu",
    "punjabi": "pa",
    "urdu": "ur",
    "spanish": "es",
    "french": "fr",
    "german": "de",
}

_LANGUAGE_NAME_ALLOWED = re.compile(r"[^\w\s().\-]", re.UNICODE)


def _is_word_char(ch: str) -> bool:
    # L* letters, M* combining marks (vowel signs), N* digits.
    return unicodedata.category(ch)[0] in {"L", "M", "N"}


def tokenize_words(text: str) -> list[str]:
    """Split text into lowercase word tokens for any script.

    Letters, combining marks and digits form words; an apostrophe is kept only
    *inside* a word ("don't"). Everything else separates words.
    """
    text = unicodedata.normalize("NFC", text or "").casefold()
    tokens: list[str] = []
    current: list[str] = []
    for index, ch in enumerate(text):
        if _is_word_char(ch):
            current.append(ch)
        elif ch in _APOSTROPHES and current and index + 1 < len(text) and _is_word_char(text[index + 1]):
            current.append("'")
        else:
            if current:
                tokens.append("".join(current))
                current = []
    if current:
        tokens.append("".join(current))
    return tokens


def clean_language_name(language: str | None) -> str:
    """A prompt-safe language label: letters, spaces and a few separators only,
    one line, at most 40 characters. Empty string when nothing usable remains."""
    if not language or not language.strip():
        return ""
    first_line = language.strip().splitlines()[0]
    cleaned = _LANGUAGE_NAME_ALLOWED.sub("", unicodedata.normalize("NFKC", first_line))
    cleaned = " ".join(cleaned.split())
    return cleaned[:40].strip()


def language_code(language: str | None) -> str | None:
    """ISO-639-1 code for a language name, or None when it isn't recognised
    (callers then let the provider auto-detect rather than guess)."""
    name = clean_language_name(language).casefold()
    if not name:
        return None
    if name in _LANGUAGE_CODES:
        return _LANGUAGE_CODES[name]
    first = name.split()[0].strip("()")
    return _LANGUAGE_CODES.get(first)
