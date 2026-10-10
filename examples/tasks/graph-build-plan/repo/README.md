# buildplan

Computes build orders for the monorepo. A spec file lists each target and what it needs:

```text
# spec.txt
app: lib util
lib: core
util: core
core:
```

```sh
python -m buildplan spec.txt        # prints core, lib, util, app (one per line)
```

* `graph.py`  `Graph`: `add_node(name)`, `add_dep(node, dep)`, `nodes()`, `deps(node)`; `GraphError`
* `spec.py`   `parse_spec(text)` -> `Graph`; `SpecError`
* `order.py`  `topo_order(graph)`: dependencies first
* `cycles.py` `CycleError`
* `cli.py`    `main(argv=None, out=None, err=None)` -> exit status

Run the tests with `python -m unittest discover -s tests -t .`.
