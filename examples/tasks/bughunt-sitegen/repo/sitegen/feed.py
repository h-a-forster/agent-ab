"""RSS feed and sitemap generation."""

from .util import escape_html, join_url

_DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def rfc822(date):
    """``date(2024, 3, 5)`` -> ``"Tue, 05 Mar 2024 00:00:00 +0000"`` (locale independent)."""
    return "%s, %02d %s %04d 00:00:00 +0000" % (_DAYS[date.weekday()], date.day, _MONTHS[date.month - 1], date.year)


def build_feed(title, base_url, pages, limit=10):
    """RSS 2.0 text for the first ``limit`` *dated* pages of ``pages`` (caller supplies the order)."""
    entries = [p for p in pages if p.date is not None][:limit]
    lines = ['<?xml version="1.0" encoding="UTF-8"?>', '<rss version="2.0">', "<channel>",
             "<title>%s</title>" % escape_html(title), "<link>%s</link>" % escape_html(base_url.rstrip("/") + "/")]
    for page in entries:
        link = join_url(base_url, page.url)
        lines.extend([
            "<item>",
            "<title>%s</title>" % escape_html(page.title),
            "<link>%s</link>" % escape_html(link),
            "<guid>%s</guid>" % escape_html(link),
            "<pubDate>%s</pubDate>" % rfc822(page.date),
            "</item>",
        ])
    lines.extend(["</channel>", "</rss>"])
    return "\n".join(lines) + "\n"


def build_sitemap(base_url, pages):
    """``<urlset>`` listing each page once, sorted by URL; dated pages get ``<lastmod>``."""
    lines = ['<?xml version="1.0" encoding="UTF-8"?>', '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for page in sorted(pages, key=lambda p: p.url):
        lines.append("<url>")
        lines.append("<loc>%s</loc>" % escape_html(join_url(base_url, page.url)))
        if page.date is not None:
            lines.append("<lastmod>%s</lastmod>" % page.date.isoformat())
        lines.append("</url>")
    lines.append("</urlset>")
    return "\n".join(lines) + "\n"
