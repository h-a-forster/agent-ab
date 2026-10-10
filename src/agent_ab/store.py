"""Run directory: metadata, the append-only trial log, and per-attempt artifact folders.

The log is the single source of truth. Each attempt is appended as one JSON line and
fsynced, so a crash or Ctrl-C loses at most the attempt in flight and a run can always
be resumed from what is on disk.
"""

from __future__ import annotations

import json
import math
import os
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agent_ab import __version__
from agent_ab.config import FINGERPRINT_SCHEME, experiment_to_dict
from agent_ab.errors import RunStoreError
from agent_ab.model import SCHEMA_VERSION, Experiment, TrialRecord

RUN_FILE = "run.json"
TRIALS_FILE = "trials.jsonl"
TRIALS_DIR = "trials"
MAX_COST_USD = 1e6  # an agent-reported cost above this per attempt is treated as unknown


def utc_now() -> str:
    """Current time as an ISO-8601 UTC string with second precision."""
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class RunStore:
    """Read and write one run directory. ``append`` is safe to call from several threads."""

    def __init__(self, run_dir: Path):
        # Absolute, because artifact paths are handed to agents whose cwd is elsewhere.
        self.run_dir = Path(run_dir).resolve()
        self.meta: dict[str, Any] = {}
        self._lock = threading.Lock()
        self._tail_checked = False  # the log's tail is repaired once, before the first append

    # ------------------------------------------------------------------ lifecycle

    @classmethod
    def create(cls, run_dir: Path, exp: Experiment, planned_trials: int) -> RunStore:
        """Start a new run directory.

        Refuses a directory that already holds a run or leftovers of one (a trial log or
        artifact folders without run.json): appending to stale records would silently mix
        two experiments.
        """
        run_dir = Path(run_dir)
        check_new_run_dir(run_dir)
        run_dir.mkdir(parents=True, exist_ok=True)
        store = cls(run_dir)
        store.meta = {
            "schema": SCHEMA_VERSION,
            "tool": "agent-ab",
            "version": __version__,
            "experiment": exp.name,
            "fingerprint": exp.fingerprint,
            "fingerprint_scheme": FINGERPRINT_SCHEME,
            "created_at": utc_now(),
            "config": _redact_env(experiment_to_dict(exp, store.run_dir)),
            "planned_trials": planned_trials,
            "seed": exp.seed,
            "baseline": exp.baseline,
        }
        try:
            # "x": never adopt a log that appeared since the check above.
            with open(run_dir / TRIALS_FILE, "x", encoding="utf-8"):
                pass
        except FileExistsError as e:
            raise RunStoreError(f"{run_dir / TRIALS_FILE} appeared while creating the run") from e
        store._write_meta()
        return store

    @classmethod
    def open(cls, run_dir: Path) -> RunStore:
        """Open an existing run directory."""
        run_dir = Path(run_dir)
        path = run_dir / RUN_FILE
        if not path.is_file():
            raise RunStoreError(f"{run_dir} is not an agent-ab run directory (no {RUN_FILE})")
        try:
            meta = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            raise RunStoreError(f"cannot read {path}: {e}") from e
        if not isinstance(meta, dict) or meta.get("tool") != "agent-ab":
            raise RunStoreError(f"{path} was not written by agent-ab")
        if meta.get("schema", 0) > SCHEMA_VERSION:
            raise RunStoreError(
                f"{path} uses schema {meta.get('schema')}; this agent-ab understands "
                f"up to {SCHEMA_VERSION}. Upgrade agent-ab to read it."
            )
        store = cls(run_dir)
        store.meta = meta
        return store

    def check_compatible(self, exp: Experiment, *, force: bool = False) -> None:
        """Refuse to resume a run with a different experiment definition unless forced."""
        if self.meta.get("experiment") != exp.name and not force:
            raise RunStoreError(
                f"run belongs to experiment {self.meta.get('experiment')!r}, not {exp.name!r}"
            )
        if self.meta.get("fingerprint") != exp.fingerprint and not force:
            if self.meta.get("fingerprint_scheme", 1) != FINGERPRINT_SCHEME:
                raise RunStoreError(
                    "this run was started by an older agent-ab whose fingerprint depended on the "
                    "checkout location, so it cannot be compared with the current experiment. "
                    "Pass --force to resume anyway if you know the experiment is unchanged, "
                    "or start a new run."
                )
            raise RunStoreError(
                "the experiment (config, tasks or overlays) changed since this run started; "
                "mixing trials would bias the comparison. Start a new run, or pass --force "
                "to resume anyway."
            )

    def update_meta(self, **changes: Any) -> None:
        """Merge ``changes`` into run.json (e.g. a new planned-trial count after a resume)."""
        with self._lock:
            self.meta.update(changes)
            self._write_meta()

    def _write_meta(self) -> None:
        path = self.run_dir / RUN_FILE
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(self.meta, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(tmp, path)

    # ------------------------------------------------------------------ trial log

    def append(self, record: TrialRecord) -> None:
        """Durably append one attempt to the log."""
        line = json.dumps(record.to_dict(), sort_keys=True, allow_nan=False) + "\n"
        with self._lock:
            if not self._tail_checked:
                self._repair_tail()
                self._tail_checked = True
            with open(self.run_dir / TRIALS_FILE, "a", encoding="utf-8", newline="\n") as f:
                f.write(line)
                f.flush()
                os.fsync(f.fileno())

    def _repair_tail(self) -> None:
        """Make the log end in a complete, valid line before appending to it.

        An interrupted write leaves a partial last line that ``records`` tolerates only while
        it stays last; appending would glue the next record onto it or bury it mid-file and
        make the whole log unreadable. A damaged last line is moved to a side file (kept as
        evidence) and cut off; a valid one that only lacks its newline gets the newline.
        """
        path = self.run_dir / TRIALS_FILE
        try:
            data = path.read_bytes()
        except FileNotFoundError:
            return
        except OSError as e:
            raise RunStoreError(f"cannot read {path}: {e}") from e
        body = data.rstrip(b"\r\n\t ")
        if not body:
            return
        start = body.rfind(b"\n") + 1
        if _parses(body[start:]):
            if not data.endswith(b"\n"):
                with open(path, "ab") as f:
                    f.write(b"\n")
                    f.flush()
                    os.fsync(f.fileno())
            return
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        side = path.with_name(f"{TRIALS_FILE}.damaged-{stamp}")
        try:
            with open(side, "xb") as f:
                f.write(data[start:])
                f.flush()
                os.fsync(f.fileno())
            with open(path, "r+b") as f:
                f.truncate(start)
                f.flush()
                os.fsync(f.fileno())
        except OSError as e:
            raise RunStoreError(f"cannot repair the damaged last line of {path}: {e}") from e

    def records(self) -> list[TrialRecord]:
        """Every recorded attempt in log order.

        A damaged final line is what an interrupted write looks like, so it is skipped;
        damage anywhere else means the file was edited or corrupted and is an error.
        """
        path = self.run_dir / TRIALS_FILE
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except FileNotFoundError:
            return []
        except OSError as e:
            raise RunStoreError(f"cannot read {path}: {e}") from e
        lines = text.splitlines()
        # Trailing blank lines do not make an earlier damaged line "mid-file".
        last = max((i for i, line in enumerate(lines) if line.strip()), default=-1)
        out: list[TrialRecord] = []
        for i, line in enumerate(lines):
            if not line.strip():
                continue
            try:
                data = json.loads(line)
                if not isinstance(data, dict):
                    raise ValueError("not an object")
                out.append(TrialRecord.from_dict(data))
            except (ValueError, TypeError) as e:
                if i == last:
                    break
                raise RunStoreError(f"{path}: line {i + 1} is corrupt ({e})") from e
        return out

    def final_records(self) -> dict[str, TrialRecord]:
        """The latest attempt for each trial id."""
        final: dict[str, TrialRecord] = {}
        for rec in self.records():
            prev = final.get(rec.trial_id)
            if prev is None or rec.attempt >= prev.attempt:
                final[rec.trial_id] = rec
        return final

    def total_cost(self) -> float:
        """Spend across every attempt, including retried ones: retries cost money too."""
        return math.fsum(_cost(r) for r in self.records())

    # ------------------------------------------------------------------ artifacts

    def attempt_dir(self, trial_id: str, attempt: int) -> Path:
        """Create and return the artifact folder for one attempt."""
        path = self.run_dir / TRIALS_DIR / trial_id / f"attempt-{attempt}"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def relpath(self, path: Path) -> str:
        """Run-dir-relative posix path, as stored in records."""
        return Path(path).resolve().relative_to(self.run_dir.resolve()).as_posix()


def check_new_run_dir(run_dir: Path) -> None:
    """Raise ``RunStoreError`` unless ``run_dir`` is free for a new run (absent or unrelated)."""
    run_dir = Path(run_dir)
    if (run_dir / RUN_FILE).exists():
        raise RunStoreError(f"{run_dir} already contains a run; use --resume to continue it")
    leftovers = [n for n in (TRIALS_FILE, TRIALS_DIR) if os.path.lexists(run_dir / n)]
    if leftovers:
        raise RunStoreError(
            f"{run_dir} holds agent-ab results ({', '.join(leftovers)}) but no {RUN_FILE}; "
            "refusing to mix them into a new run. Choose another directory or remove them."
        )


def _cost(record: TrialRecord) -> float:
    # Logs written by older versions may hold absurd agent-reported costs (huge ints, 1e308)
    # that would overflow the sum and wedge the budget forever; such values count as unknown.
    c = record.cost_usd
    if isinstance(c, bool) or not isinstance(c, (int, float)) or not 0 <= c <= MAX_COST_USD:
        return 0.0
    return float(c)


def _parses(line: bytes) -> bool:
    try:
        data = json.loads(line.decode("utf-8"))
        if not isinstance(data, dict):
            return False
        TrialRecord.from_dict(data)
    except (ValueError, TypeError):
        return False
    return True


def _redact_env(value: Any) -> Any:
    """Drop environment values from stored config: they often hold credentials.

    Keys stay so a reader can see which variables were set; the fingerprint, computed
    from the unredacted config, still detects changed values on resume.
    """
    if isinstance(value, dict):
        return {
            k: (
                {name: "<redacted>" for name in v}
                if k == "env" and isinstance(v, dict)
                else _redact_env(v)
            )
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [_redact_env(v) for v in value]
    return value


def is_done(record: TrialRecord, max_retries: int) -> bool:
    """A trial needs no more attempts once it passed/failed or exhausted its retries."""
    return record.status in ("pass", "fail") or record.attempt >= max_retries
