"""Masking sensitive values."""

import re

_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@([A-Za-z0-9.-]+\.[A-Za-z]{2,})")
_TOKEN = re.compile(r"\b(?:token|secret|password|passwd|apikey)=([^\s&\"']+)", re.IGNORECASE)
_CARD = re.compile(r"\b\d(?:[ -]?\d){12,15}\b")


def mask_email(text):
    """``alice@example.com`` -> ``***@example.com`` (the domain stays)."""
    return _EMAIL.sub(lambda m: "***@" + m.group(1), text)


def mask_tokens(text):
    """``password=hunter2`` -> ``password=[redacted]``."""
    return _TOKEN.sub(lambda m: m.group(0)[:m.start(1) - m.start(0)] + "[redacted]", text)


def mask_cards(text):
    """Card-like digit runs keep only their last four digits: ``4111 1111 1111 1111`` -> ``************1111``."""

    def repl(match):
        digits = re.sub(r"\D", "", match.group(0))
        if not 13 <= len(digits) <= 16:
            return match.group(0)
        return "*" * (len(digits) - 4) + digits[-4:]

    return _CARD.sub(repl, text)


def redact_text(text):
    return mask_cards(mask_tokens(mask_email(text)))


def redact_record(record, fields=()):
    """Redact the message and the named string fields in place; returns the record."""
    record.msg = redact_text(record.msg)
    for name in fields:
        value = record.fields.get(name)
        if isinstance(value, str):
            record.fields[name] = redact_text(value)
    return record
