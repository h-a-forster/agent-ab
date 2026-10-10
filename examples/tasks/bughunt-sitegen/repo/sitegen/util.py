"""Small shared helpers."""

import re
import unicodedata

_NON_WORD = re.compile(r"[^\w\s-]", re.UNICODE)
_SEPARATORS = re.compile(r"[\s_-]+", re.UNICODE)


def slugify(text):
    """``"Hello, World!"`` -> ``"hello-world"``; accents are removed (``"Café"`` -> ``"cafe"``)."""
    folded = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    folded = _NON_WORD.sub("", folded.lower())
    return _SEPARATORS.sub("-", folded).strip("-")


def ensure_slashes(url):
    """Make a URL path start and end with ``/`` (``"blog"`` -> ``"/blog/"``)."""
    if not url.startswith("/"):
        url = "/" + url
    if not url.endswith("/"):
        url += "/"
    return url


def url_to_path(url):
    """Output file for a page URL: ``"/a/b/"`` -> ``"a/b/index.html"``, ``"/"`` -> ``"index.html"``,
    ``"/feed.xml"`` -> ``"feed.xml"``."""
    stripped = url.lstrip("/")
    if url.endswith("/") or stripped == "":
        return stripped + "index.html"
    return stripped


def join_url(base, *parts):
    """Join URL pieces with single slashes: ``join_url("https://x.org/", "/a", "b/")`` is
    ``"https://x.org/a/b/"``; a trailing slash on the last piece is kept, empty pieces are skipped."""
    segments = [p.strip("/") for p in parts if p.strip("/")]
    out = base.rstrip("/") + "".join("/" + seg for seg in segments)
    if not segments or parts[-1].endswith("/"):
        out += "/"
    return out


def escape_html(text):
    return (str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;"))
