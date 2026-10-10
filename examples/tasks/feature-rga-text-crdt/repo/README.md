# crdtext

Shared text editing for a collaborative notes app.

* `document.py` `Document`: a plain list-of-characters text with `insert` / `delete` by index
* `session.py`  `Session`: a central server applying client edits in arrival order. Two clients
                typing at the same time against stale indexes corrupt each other's edits, so the
                app is moving to replicas that merge without a server.

Run the tests with `python -m unittest discover -s tests -t .`.
