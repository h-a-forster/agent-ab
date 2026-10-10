"""Resolving relative links between source files."""

import posixpath
import re

_LINK = re.compile(r"(\[[^\]]*\]\()([^)\s]+)(\))")


def split_fragment(target):
    path, sep, fragment = target.partition("#")
    return path, (sep + fragment if sep else "")


def is_external(target):
    return bool(re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", target)) or target.startswith("//")


def resolve_source(current_source, target_path):
    """Source path that ``target_path`` refers to when written inside ``current_source``.

    Paths starting with ``/`` are relative to the site root; others to the directory of the
    current file.  ``..`` and ``.`` segments are collapsed.
    """
    if target_path.startswith("/"):
        return posixpath.normpath(target_path.lstrip("/"))
    base = posixpath.dirname(current_source)
    return posixpath.join(base, target_path)


def rewrite_links(body, current_source, url_by_source, broken=None):
    """Replace links to ``*.md`` files by the target page's URL (a ``#fragment`` is kept).

    External links, plain fragments and non-markdown targets are left alone.  Unknown ``.md``
    targets stay as written and are appended to ``broken`` as ``(current_source, target)``.
    """

    def replace(match):
        head, target, tail = match.groups()
        if is_external(target) or target.startswith("#"):
            return match.group(0)
        path, fragment = split_fragment(target)
        if not path.endswith(".md"):
            return match.group(0)
        source = resolve_source(current_source, path)
        url = url_by_source.get(source)
        if url is None:
            if broken is not None:
                broken.append((current_source, target))
            return match.group(0)
        return head + url + fragment + tail

    return _LINK.sub(replace, body)
