# hsm

A small finite-state-machine library used by the device firmware simulator.

```python
from hsm import Machine, Transition

log = []
m = Machine(
    states=["idle", "running"],
    transitions=[
        Transition("idle", "start", "running", action=lambda p: log.append("go")),
        Transition("running", "stop", "idle"),
        Transition("running", "tick", None, action=lambda p: log.append("tick")),  # internal
    ],
    initial="idle",
    on_enter={"running": lambda p: log.append("enter running")},
)
m.send("start")      # True
m.state              # 'running'
```

* `states.py`       the set of declared state names
* `transitions.py`  the `Transition` record
* `machine.py`      `Machine`: `send(event, **payload)`, `state`, `is_in(name)`, `configuration()`

Callbacks (`guard`, `action`, `on_enter`, `on_exit`) all receive the event payload as one dict.
Constructing a machine runs the `on_enter` callback of the initial state with an empty payload.
A transition with `target=None` is internal: only its action runs. A transition whose target
is its own source is external: the state is exited and entered again.

Run the tests with `python -m unittest discover -s tests -t .`.
