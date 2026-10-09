# pagekit

Tiny helpers for paginating in-memory sequences (search results, admin tables, API listings).

```python
from pagekit import paginate

page = paginate(list(range(1, 11)), page=2, per_page=3)
page.items        # [4, 5, 6]
page.total_pages  # 4
```

Run the tests with `python -m unittest discover -s tests -t .`.
