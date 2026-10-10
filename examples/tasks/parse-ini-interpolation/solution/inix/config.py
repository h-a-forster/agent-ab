"""The :class:`Config` container."""

from __future__ import annotations

from .interpolate import interpolate
from .parser import parse

_MISSING = object()
_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"0", "false", "no", "off"}


class MissingError(KeyError):
    """A section or key does not exist."""


class Config:
    def __init__(self, data: dict[str, dict[str, str]] | None = None) -> None:
        self._data: dict[str, dict[str, str]] = {s: dict(v) for s, v in (data or {}).items()}

    @classmethod
    def from_string(cls, text: str) -> "Config":
        return cls(parse(text))

    def sections(self) -> list[str]:
        return list(self._data)

    def keys(self, section: str) -> list[str]:
        if section not in self._data:
            raise MissingError(f"no such section: {section}")
        return list(self._data[section])

    def has(self, section: str, key: str) -> bool:
        return key in self._data.get(section, {})

    def set(self, section: str, key: str, value: str) -> None:
        self._data.setdefault(section, {})[key] = str(value)

    def _lookup(self, section: str, key: str) -> str | None:
        return self._data.get(section, {}).get(key)

    def get(self, section: str, key: str, fallback=_MISSING, raw: bool = False) -> str:
        raw_value = self._lookup(section, key)
        if raw_value is None:
            if fallback is not _MISSING:
                return fallback
            raise MissingError(f"no such key: {section}.{key}")
        if raw:
            return raw_value
        return interpolate(raw_value, section, self._lookup, ((section, key),))

    def items(self, section: str, raw: bool = False) -> dict[str, str]:
        if section not in self._data:
            raise MissingError(f"no such section: {section}")
        return {key: self.get(section, key, raw=raw) for key in self._data[section]}

    def getint(self, section: str, key: str, fallback=_MISSING) -> int:
        value = self.get(section, key, fallback)
        return value if value is fallback else int(value)

    def getfloat(self, section: str, key: str, fallback=_MISSING) -> float:
        value = self.get(section, key, fallback)
        return value if value is fallback else float(value)

    def getbool(self, section: str, key: str, fallback=_MISSING) -> bool:
        value = self.get(section, key, fallback)
        if value is fallback:
            return value
        lowered = value.strip().lower()
        if lowered in _TRUE:
            return True
        if lowered in _FALSE:
            return False
        raise ValueError(f"not a boolean: {value!r}")
