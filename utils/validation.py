from __future__ import annotations

import difflib
import re
import unicodedata

from core.models import SuggestionType

MAX_NAME_LENGTH = 100
MAX_REASON_LENGTH = 1000
SIMILARITY_THRESHOLD = 0.85

_HEX_RE = re.compile(r"#?([0-9a-fA-F]{6})")


class ValidationError(ValueError):
    pass


def slugify_channel_name(raw: str) -> str:
    # "Off Topic  Gaming!" -> "off-topic-gaming" (Umlaute bleiben, Discord erlaubt sie)
    text = unicodedata.normalize("NFKC", raw).strip().lower()
    text = re.sub(r"\s+", "-", text)
    text = re.sub(r"[^\w-]", "", text)
    text = re.sub(r"-{2,}", "-", text)
    return text.strip("-_")


def normalize_role_name(raw: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", raw)).strip()


def validate_name(raw: str, s_type: SuggestionType) -> str:
    if len(raw.strip()) > MAX_NAME_LENGTH:
        raise ValidationError(f"Der Name ist zu lang (max. {MAX_NAME_LENGTH} Zeichen).")

    if s_type is SuggestionType.CHANNEL:
        name = slugify_channel_name(raw)
    else:
        name = normalize_role_name(raw)

    if not name:
        raise ValidationError("Der Name ist leer oder enthält keine gültigen Zeichen.")

    return name


def validate_reason(raw: str) -> str:
    reason = raw.strip()

    if not reason:
        raise ValidationError("Bitte gib eine Begründung an.")

    if len(reason) > MAX_REASON_LENGTH:
        raise ValidationError(f"Die Begründung ist zu lang (max. {MAX_REASON_LENGTH} Zeichen).")

    return reason


def normalize_hex_color(raw: str | None) -> str | None:
    if raw is None or not raw.strip():
        return None

    match = _HEX_RE.fullmatch(raw.strip())

    if not match:
        raise ValidationError("Ungültige Farbe – erwartet wird ein Hex-Wert wie `#5865F2`.")

    return "#" + match.group(1).upper()


def is_similar(a: str, b: str) -> bool:
    # Vergleich auf Slug-Basis, damit "Off Topic" ~ "off-topic"
    key_a = slugify_channel_name(a)
    key_b = slugify_channel_name(b)

    if not key_a or not key_b:
        return False

    return key_a == key_b or difflib.SequenceMatcher(None, key_a, key_b).ratio() >= SIMILARITY_THRESHOLD
