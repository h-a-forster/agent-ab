"""Derived fields added to records."""

import re

_IPV4 = re.compile(r"^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$")


def subnet(ip, prefix=24):
    """``"10.1.2.3"`` -> ``"10.1.2.0/24"``.  Only prefixes 8, 16 and 24 are supported; anything
    that is not an IPv4 address gives ``None``."""
    m = _IPV4.match(str(ip))
    if not m or prefix not in (8, 16, 24):
        return None
    parts = [int(g) for g in m.groups()]
    if any(p > 255 for p in parts):
        return None
    keep = prefix // 8
    masked = parts[:keep] + [0] * (4 - keep)
    return "%s/%d" % (".".join(str(p) for p in masked), prefix)


def status_class(status):
    """``404`` -> ``"4xx"``; non-numeric or out-of-range input gives ``None``."""
    try:
        status = int(status)
    except (TypeError, ValueError):
        return None
    if not 100 <= status <= 599:
        return None
    return "%dxx" % (status // 100)


def user_agent_family(agent):
    text = str(agent).lower()
    for needle, family in (("firefox", "firefox"), ("chrome", "chrome"), ("safari", "safari"), ("curl", "curl")):
        if needle in text:
            return family
    return "other"


class Enricher:
    """Adds ``subnet`` (from ``ip``), ``status_class`` (from ``status``) and ``agent_family``
    (from ``agent``) fields, on top of constant ``defaults`` such as ``{"env": "prod"}``.

    A record's own fields win over the defaults; every record gets its own fields dict and the
    defaults are never modified.
    """

    def __init__(self, defaults=None, prefix=24):
        self.defaults = dict(defaults or {})
        self.prefix = prefix

    def enrich(self, record):
        fields = self.defaults
        fields.update(record.fields)
        ip = fields.get("ip")
        if ip is not None and subnet(ip, self.prefix):
            fields["subnet"] = subnet(ip, self.prefix)
        if "status" in fields and status_class(fields["status"]):
            fields["status_class"] = status_class(fields["status"])
        if "agent" in fields:
            fields["agent_family"] = user_agent_family(fields["agent"])
        record.fields = fields
        return record
