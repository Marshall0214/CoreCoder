"""Conservative input-truncation evidence from supplied Ollama log text only."""
import re

_RELATED = re.compile(r'truncat', re.IGNORECASE)
_INPUT_WARNING = re.compile(
    r'\btruncating\s+(?:the\s+)?input\s+prompt\b'
    r'|\b(?:input(?:\s+prompt)?|prompt)\s+(?:(?:was|is|has\s+been|had\s+been)\s+)?truncated\b'
    r'|\btruncated\s+(?:the\s+)?input(?:\s+prompt)?\s+(?:from|to)\s+\d+'
    r'|\binput(?:\s+prompt)?\s+truncation\s+(?:occurred|detected|applied)\b'
    r'|\binput_truncated[\"\']?\s*[:=]\s*(?:true|[1-9]\d*)\b',
    re.IGNORECASE,
)
_NEGATED_ACTION = re.compile(r'\b(?:not|never|without|no\s+longer)\s+truncat', re.IGNORECASE)
_ZERO_FIELD = re.compile(
    r'\b(?:input_)?truncated[\"\']?\s*[:=]\s*(?:0|false)(?=[\s,;}\]]|$)', re.IGNORECASE)
_NON_INPUT = re.compile(
    r'\b(?:output|response|completion|stderr|stdout|log)\s+(?:(?:was|is)\s+)?truncat'
    r'|\btruncat\w*\s+(?:the\s+)?(?:output|response|completion|stderr|stdout|log)\b',
    re.IGNORECASE,
)


def classify(text):
    """Retain raw lines; normal zero flags never establish complete input delivery.

    A positive result confirms an explicit input-truncation log statement, not
    its request attribution or which source tokens the server retained.
    Unrecognized messages remain ambiguous rather than becoming warnings.
    """
    if not isinstance(text, str):
        raise TypeError('Supply decoded log text')
    related, confirmed, zero, unrelated, ambiguous = [], [], [], [], []
    for raw in text.splitlines():
        if not _RELATED.search(raw):
            continue
        related.append(raw)
        # Match a normalized view while retaining the exact original line.
        line = ' '.join(raw.split())
        positive = bool(_INPUT_WARNING.search(line))
        negative = bool(_NEGATED_ACTION.search(line))
        zero_field = bool(_ZERO_FIELD.search(line))
        if positive and not negative and not zero_field:
            confirmed.append(raw)
        elif positive:
            # Contradictory/negated evidence must not produce a positive claim.
            ambiguous.append(raw)
        elif zero_field:
            zero.append(raw)
        elif _NON_INPUT.search(line):
            unrelated.append(raw)
        else:
            ambiguous.append(raw)
    return {'server_input_truncation': 'warning_observed' if confirmed else 'not_verified',
            'raw_truncation_related_lines': related,
            'confirmed_input_truncation_warnings': confirmed,
            'normal_zero_truncation_lines': zero,
            'non_input_truncation_lines': unrelated,
            'ambiguous_truncation_lines': ambiguous,
            'input_completeness_verified': False,
            'scope': 'Classification of supplied log statements; no proof of complete input or request attribution'}
