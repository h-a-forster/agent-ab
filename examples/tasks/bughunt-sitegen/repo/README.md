# sitegen

A tiny static site generator that works on in-memory files: Markdown pages with front
matter, permalinks, tags, a paginated blog index, an RSS feed, a sitemap, relative link
rewriting and a small template language.

```python
from sitegen import Site

files = {
    "index.md": "---\ntitle: Home\n---\nHello, see [about](about.md).",
    "about.md": "About us",
    "posts/2024-03-05-hello.md": "---\ntitle: Hello\ntags: [news]\n---\nFirst post",
}
site = Site(files, {"permalinks": {"posts": "/blog/{year}/{month}/{slug}/"}})
output = site.build()           # {"index.html": ..., "blog/2024/03/hello/index.html": ..., "feed.xml": ...}
```

Documented behaviour:

* Front matter lines are `key: value`; the value is everything after the **first** colon
  (`title: Hello: World` is the title `Hello: World`).
* Permalink placeholders: `{slug} {year} {month} {day} {section} {title}`; month and day are
  zero padded (`2024/03/05`). Order of precedence: `url:` in the front matter, `permalink:` in
  the front matter, `index.md` (its directory), the pattern of the page's section, the
  `default` pattern, `/{slug}/`.
* Pagination: `ceil(n / per_page)` pages (at least one); page 1 is at the base URL, page `k` at
  `<base>page/<k>/`.
* Ordering: newest first; pages with the same date are ordered by title, A to Z
  (case-insensitive). This applies to the blog index, tag pages, feeds and neighbours.
* Drafts (`draft: true`) are not part of the site: not rendered, not listed on the blog index or
  tag pages, **not in the feed and not in the sitemap**, unless `include_drafts` is set.
* Links to other `.md` files are written relative to the file containing them and are turned
  into page URLs (`../about.md#team` -> `/about/#team`); `.` and `..` segments are
  collapsed. Unknown targets are left as written and reported in `site.broken_links`.
* Templates: a `{% for x in xs %}` loop has its own scope: the loop variable and `loop` do not
  exist after the loop and never overwrite a variable of the same name defined outside it.
  Nested loops each have their own `loop`.

Run the tests with `python -m unittest discover -s tests -t .`.
