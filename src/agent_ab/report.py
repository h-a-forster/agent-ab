"""Render an ``Analysis`` as text, Markdown, JSON or a self-contained HTML page.

Renderers are pure functions of the analysis: no I/O, no clock, no randomness, so the same
analysis always produces byte-identical output.
"""

from __future__ import annotations

import dataclasses
import html
import json
import math
from collections.abc import Iterable, Sequence
from typing import Any

from .model import Analysis, ArmSummary, Comparison, Interval, TaskCell

JSON_SCHEMA = 1
HEATMAP_FULL_LIMIT = 60  # above this many tasks, agreeing tasks collapse into <details>
FLAKY_INLINE_LIMIT = 40

_VERDICT_SHORT = {
    "better": "higher pass rate",
    "worse": "lower pass rate",
    "no detectable difference": "no detectable difference",
    "insufficient data": "insufficient data",
}


# --------------------------------------------------------------------------- formatting


def _num(x: Any) -> float | None:
    """Finite float or None (NaN/inf and missing values all print as "-")."""
    if x is None or isinstance(x, bool):
        return None
    try:
        f = float(x)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def fmt_pct(x: float | None, digits: int = 1) -> str:
    """Rate as a percentage: 0.417 -> "41.7%"."""
    v = _num(x)
    return "-" if v is None else f"{v * 100:.{digits}f}%"


def fmt_pts(x: float | None, *, unit: bool = True) -> str:
    """Signed rate difference in percentage points: 0.042 -> "+4.2 pts"."""
    v = _num(x)
    if v is None:
        return "-"
    s = f"{v * 100:+.1f}"
    if s in ("+0.0", "-0.0"):
        s = "0.0"
    return f"{s} pts" if unit else s


def fmt_cost(x: float | None) -> str:
    """Dollar amount with precision that suits its size: "$1.23", "$0.312", "$0.0123"."""
    v = _num(x)
    if v is None:
        return "-"
    if v == 0:
        return "$0.00"
    a = abs(v)
    if a >= 1:
        s = f"{a:,.2f}"
    elif a >= 0.1:
        s = f"{a:.3f}"
    elif a >= 0.0001:
        s = f"{a:.4f}"
    else:
        return "<$0.0001" if v > 0 else "-<$0.0001"
    return ("-$" if v < 0 else "$") + s


def fmt_duration(x: float | None) -> str:
    """Seconds as "41.2s", "3m 05s" or "1h 02m"."""
    v = _num(x)
    if v is None:
        return "-"
    if v < 60:
        return f"{v:.1f}s"
    total = int(round(v))
    if total < 3600:
        return f"{total // 60}m {total % 60:02d}s"
    return f"{total // 3600}h {(total % 3600) // 60:02d}m"


def fmt_ratio(x: float | None) -> str:
    v = _num(x)
    return "-" if v is None else f"x{v:.2f}"


def fmt_p(x: float | None) -> str:
    v = _num(x)
    if v is None:
        return "-"
    if v < 0.001:
        return "<0.001"
    return f"{v:.2f}" if v >= 0.095 else f"{v:.3f}"


def fmt_count(x: float | None) -> str:
    """Compact count: 950.4 -> "950", 1234 -> "1.2k", 12345 -> "12k", 2.5e6 -> "2.5M"."""
    v = _num(x)
    if v is None:
        return "-"
    if abs(v) >= 1e6:
        return f"{v / 1e6:.1f}M"
    if abs(v) >= 1e4:
        return f"{v / 1e3:.0f}k"
    if abs(v) >= 1e3:
        return f"{v / 1e3:.1f}k"
    return f"{v:.0f}"


def _tokens(arm: ArmSummary) -> str:
    if _num(arm.mean_input_tokens) is None and _num(arm.mean_output_tokens) is None:
        return "-"
    return f"{fmt_count(arm.mean_input_tokens)}/{fmt_count(arm.mean_output_tokens)}"


def _ci_level(alpha: float) -> str:
    a = _num(alpha)
    return "CI" if a is None else f"{(1 - a) * 100:g}% CI"


def _pts_ci(iv: Interval) -> str:
    """"[-6.1, +14.5]" in points, or "" when the interval is unknown."""
    if _num(iv.low) is None or _num(iv.high) is None:
        return ""
    return f"[{fmt_pts(iv.low, unit=False)}, {fmt_pts(iv.high, unit=False)}]"


def _ratio_ci(iv: Interval) -> str:
    est = fmt_ratio(iv.estimate)
    if est == "-" or _num(iv.low) is None or _num(iv.high) is None:
        return est
    return f"{est} [{iv.low:.2f}, {iv.high:.2f}]"


def _pct_ci(iv: Interval) -> str:
    if _num(iv.low) is None or _num(iv.high) is None:
        return "-"
    return f"{fmt_pct(iv.low)}-{fmt_pct(iv.high)}"


def _ascii(s: str) -> str:
    return str(s).encode("ascii", "replace").decode("ascii")


def _verdict_phrase(c: Comparison) -> str:
    short = _VERDICT_SHORT.get(c.verdict, str(c.verdict))
    if c.verdict == "insufficient data":
        n = c.paired_tasks
        return f"{short} ({n} paired task{'' if n == 1 else 's'})"
    return short


# --------------------------------------------------------------------------- shared views


def _arm_order(a: Analysis) -> list[str]:
    order = [s.arm for s in a.arms]
    for c in a.cells:
        if c.arm not in order:
            order.append(c.arm)
    return order


def _task_order(a: Analysis) -> list[str]:
    seen: dict[str, None] = {}
    for c in a.cells:
        seen.setdefault(c.task, None)
    return sorted(seen)


def _frac(c: TaskCell | None) -> float | None:
    if c is None or c.trials <= 0:
        return None
    return c.passes / c.trials


def _split_tasks(a: Analysis) -> tuple[list[str], list[str], dict[tuple[str, str], TaskCell]]:
    """(tasks where arms disagree, sorted by spread; remaining tasks by id; cell lookup)."""
    lookup = {(c.task, c.arm): c for c in a.cells}
    arms = _arm_order(a)
    disagree: list[tuple[float, str]] = []
    agree: list[str] = []
    for t in _task_order(a):
        fr = [f for f in (_frac(lookup.get((t, arm))) for arm in arms) if f is not None]
        spread = (max(fr) - min(fr)) if fr else 0.0
        if spread > 0:
            disagree.append((-spread, t))
        else:
            agree.append(t)
    disagree.sort()
    return [t for _, t in disagree], agree, lookup


def _cell_label(c: TaskCell | None) -> str:
    if c is None:
        return "-"
    if c.trials <= 0:
        return "err" if c.errors else "-"
    s = f"{c.passes}/{c.trials}"
    return f"{s} +{c.errors} err" if c.errors else s


def _summary_bits(a: Analysis) -> list[str]:
    n_tasks = len(_task_order(a))
    bits = [
        f"baseline {a.baseline}",
        f"{n_tasks} task{'' if n_tasks == 1 else 's'}",
        f"{a.completed_trials}/{a.planned_trials} trials completed",
        f"{a.error_trials} error{'' if a.error_trials == 1 else 's'}",
        f"total cost {fmt_cost(a.total_cost_usd)}",
        f"alpha {a.alpha:g}",
    ]
    return bits


def _headline(c: Comparison) -> str:
    """One-line comparison summary used by the text and Markdown renderers."""
    ci = _pts_ci(c.pass_rate_diff)
    diff = fmt_pts(c.pass_rate_diff.estimate) + (f" {ci}" if ci else "")
    return (
        f"{c.arm} vs {c.baseline}: {diff}, p={fmt_p(c.p_value)} "
        f"(Holm {fmt_p(c.p_value_adjusted)}) -> {_verdict_phrase(c)}; "
        f"cost {_ratio_ci(c.cost_ratio)}; time {_ratio_ci(c.duration_ratio)}"
    )


# --------------------------------------------------------------------------- text


_NBSP = "\x00"  # placeholder that _pack never breaks on


def _pack(text: str, width: int, indent: str = "", first: str = "") -> list[str]:
    """Greedy word wrap that never splits "[a, b]" groups and hard-splits overlong words."""
    tokens: list[str] = []
    depth = 0
    cur = ""
    for ch in text:
        if ch == " " and depth == 0:
            if cur:
                tokens.append(cur)
            cur = ""
            continue
        depth += ch in "[("
        depth -= ch in "])" and depth > 0
        cur += ch
    if cur:
        tokens.append(cur)
    lines: list[str] = []
    line = first
    prefix_len = len(first)
    width = max(width, len(indent) + 8, len(first) + 8)
    for tok in tokens:
        candidate = line + tok if len(line) == prefix_len else line + " " + tok
        if len(candidate) <= width:
            line = candidate
            continue
        if len(line) > prefix_len:
            lines.append(line)
            line = indent
            prefix_len = len(indent)
        while len(line) + len(tok) > width:
            room = width - len(line)
            lines.append(line + tok[:room])
            tok = tok[room:]
            line = indent
        line += tok
    if len(line) > prefix_len or not lines:
        lines.append(line)
    return [ln.rstrip().replace(_NBSP, " ") for ln in lines]


def _clip(s: str, n: int) -> str:
    return s if len(s) <= n else s[: max(n - 1, 0)] + "~"


def _text_table(
    headers: Sequence[str], rows: Sequence[Sequence[str]], right: Sequence[bool], width: int,
    drop_order: Sequence[int],
) -> list[str]:
    """Aligned columns; drops low-priority columns, then clips the first, to fit ``width``."""
    keep = list(range(len(headers)))
    gap = 2

    def widths(cols: list[int]) -> list[int]:
        return [max(len(headers[i]), *(len(r[i]) for r in rows)) if rows else len(headers[i])
                for i in cols]

    def total(cols: list[int], ws: list[int]) -> int:
        return 2 + sum(ws) + gap * (len(cols) - 1)

    ws = widths(keep)
    for i in drop_order:
        if total(keep, ws) <= width:
            break
        if i in keep:
            keep.remove(i)
            ws = widths(keep)
    over = total(keep, ws) - width
    if over > 0 and keep and keep[0] == 0:
        ws[0] = max(4, ws[0] - over)

    def fmt_row(cells: Sequence[str]) -> str:
        parts = []
        for col, w in zip(keep, ws, strict=True):
            v = _clip(cells[col], w)
            parts.append(v.rjust(w) if right[col] else v.ljust(w))
        return ("  " + (" " * gap).join(parts)).rstrip()[:width]

    lines = [fmt_row(headers), "  " + "-" * min(total(keep, ws) - 2, width - 2)]
    lines += [fmt_row(r) for r in rows]
    return lines


def render_text(a: Analysis, *, width: int = 100) -> str:
    """Plain ASCII report for terminals: verdict lines, an arm table, flaky tasks and notes."""
    width = max(int(width), 40)
    out: list[str] = []
    out += _pack(_ascii(f"agent-ab report: {a.experiment}"), width)
    bits = [b.replace(" ", _NBSP) for b in _summary_bits(a)]
    out += _pack(_ascii(" | ".join(bits)), width, indent="  ")
    out.append("")

    level = _ci_level(a.alpha)
    out.append(_clip(_ascii(f"Pass-rate difference vs {a.baseline} ({level}, paired over tasks)"),
                     width))
    if not a.comparisons:
        out.append("  No comparisons: the analysis has a single arm.")
    for c in a.comparisons:
        out += _pack(_ascii(_headline(c)), width, indent="      ", first="  ")
        noun = "task" if c.paired_tasks == 1 else "tasks"
        detail = (f"{c.paired_tasks} paired {noun}: {c.tasks_better} better, "
                  f"{c.tasks_worse} worse, {c.tasks_tied} tied")
        out += _pack(_ascii(detail), width, indent="      ", first="      ")
    out.append("")

    out.append("Arms (* = baseline)")
    headers = ["arm", "pass rate", level, "tasks", "trials", "errors", "cost/trial",
               "cost/pass", "time", "tokens in/out", "turns"]
    right = [False] + [True] * 10
    rows = []
    for s in a.arms:
        name = s.arm + (" *" if s.arm == a.baseline else "")
        rows.append([
            _ascii(name), fmt_pct(s.pass_rate.estimate), _pct_ci(s.pass_rate), str(s.tasks),
            str(s.trials), str(s.errors), fmt_cost(s.mean_cost_usd.estimate),
            fmt_cost(s.cost_per_pass_usd), fmt_duration(s.mean_duration_s.estimate),
            _tokens(s), fmt_count(s.mean_turns),
        ])
    out += _text_table(headers, rows, right, width, drop_order=[10, 9, 3, 7, 2, 4])

    if a.flaky_tasks:
        out.append("")
        out.append(f"Flaky tasks ({len(a.flaky_tasks)}; outcome varied across repeats)")
        shown = a.flaky_tasks[:FLAKY_INLINE_LIMIT]
        more = len(a.flaky_tasks) - len(shown)
        text = ", ".join(shown) + (f" and {more} more" if more > 0 else "")
        out += _pack(_ascii(text), width, indent="  ", first="  ")

    if a.notes:
        out.append("")
        out.append("Notes")
        for n in a.notes:
            out += _pack(_ascii(n), width, indent="    ", first="  - ")
    return "\n".join(ln[:width] for ln in out) + "\n"


# --------------------------------------------------------------------------- markdown

_MD_SPECIAL = set("\\`*_{}[]<>()#+!|~&")


def _md(s: Any) -> str:
    """Escape config-derived text for Markdown table cells and prose."""
    text = " ".join(str(s).split())
    return "".join("\\" + ch if ch in _MD_SPECIAL else ch for ch in text)


def _md_table(
    headers: Sequence[str], rows: Sequence[Sequence[str]], right: Sequence[bool]
) -> list[str]:
    sep = ["---:" if r else "---" for r in right]
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join(sep) + " |"]
    lines += ["| " + " | ".join(r) + " |" for r in rows]
    return lines


def render_markdown(a: Analysis) -> str:
    """GitHub-flavoured Markdown report, suitable for a pull request or README."""
    level = _ci_level(a.alpha)
    out = [f"# agent-ab report: {_md(a.experiment)}", ""]
    out.append(" · ".join(_md(b) for b in _summary_bits(a)))
    out.append("")

    out.append(f"## Pass-rate difference vs {_md(a.baseline)}")
    out.append("")
    if not a.comparisons:
        out.append("No comparisons: the analysis has a single arm.")
    else:
        rows = []
        for c in a.comparisons:
            verdict = _verdict_phrase(c)
            if c.verdict in ("better", "worse"):
                verdict = f"**{verdict}**"
            rows.append([
                _md(c.arm), fmt_pts(c.pass_rate_diff.estimate),
                _pts_ci(c.pass_rate_diff) or "-", fmt_p(c.p_value), fmt_p(c.p_value_adjusted),
                verdict, _ratio_ci(c.cost_ratio), _ratio_ci(c.duration_ratio),
                f"{c.paired_tasks} ({c.tasks_better}/{c.tasks_worse}/{c.tasks_tied})",
            ])
        out += _md_table(
            ["Arm", "Diff", f"{level} (pts)", "p", "p (Holm)", "Verdict", "Cost ratio",
             "Time ratio", "Paired tasks (better/worse/tied)"],
            rows, [False, True, True, True, True, False, True, True, True],
        )
    out.append("")

    out.append("## Arms")
    out.append("")
    rows = []
    for s in a.arms:
        name = _md(s.arm) + (" (baseline)" if s.arm == a.baseline else "")
        rows.append([
            name, fmt_pct(s.pass_rate.estimate), _pct_ci(s.pass_rate), str(s.tasks),
            str(s.trials), str(s.errors), fmt_cost(s.mean_cost_usd.estimate),
            fmt_cost(s.cost_per_pass_usd), fmt_duration(s.mean_duration_s.estimate), _tokens(s),
        ])
    out += _md_table(
        ["Arm", "Pass rate", level, "Tasks", "Trials", "Errors", "Cost/trial", "Cost/pass",
         "Time/trial", "Tokens in/out"],
        rows, [False] + [True] * 9,
    )
    out.append("")

    disagree, agree, lookup = _split_tasks(a)
    arms = _arm_order(a)
    if disagree:
        limit = 100
        out.append("<details><summary>Tasks where arms differ "
                   f"({len(disagree)} of {len(disagree) + len(agree)})</summary>")
        out.append("")
        rows = [[_md(t)] + [_cell_label(lookup.get((t, arm))) for arm in arms]
                for t in disagree[:limit]]
        out += _md_table(["Task"] + [_md(x) for x in arms], rows, [False] + [True] * len(arms))
        if len(disagree) > limit:
            out.append("")
            out.append(f"... and {len(disagree) - limit} more.")
        out.append("")
        out.append("</details>")
        out.append("")

    if a.flaky_tasks:
        out.append("## Flaky tasks")
        out.append("")
        shown = a.flaky_tasks[:FLAKY_INLINE_LIMIT]
        more = len(a.flaky_tasks) - len(shown)
        out.append(", ".join(_md(t) for t in shown)
                   + (f" and {more} more" if more > 0 else ""))
        out.append("")

    if a.notes:
        out.append("## Notes")
        out.append("")
        out += [f"- {_md(n)}" for n in a.notes]
        out.append("")

    out.append(f"<sub>Pass rate = mean over tasks of each task's pass fraction. {level}: "
               "bootstrap over tasks. p: paired sign-flip test over tasks, Holm-adjusted "
               "across comparisons.</sub>")
    return "\n".join(out) + "\n"


# --------------------------------------------------------------------------- json


def _json_safe(x: Any) -> Any:
    if isinstance(x, float):
        return x if math.isfinite(x) else None
    if isinstance(x, dict):
        return {str(k): _json_safe(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_json_safe(v) for v in x]
    return x


def render_json(a: Analysis) -> str:
    """Stable JSON: ``{"analysis": ..., "schema": 1, "tool": "agent-ab"}``, NaN/inf as null."""
    doc = {"tool": "agent-ab", "schema": JSON_SCHEMA, "analysis": _json_safe(dataclasses.asdict(a))}
    return json.dumps(doc, sort_keys=True, indent=2, allow_nan=False, ensure_ascii=False) + "\n"


# --------------------------------------------------------------------------- html

_CSS = """
:root{
  --bg:#f8f8f6;--surface:#ffffff;--fg:#1c1e21;--muted:#5d646e;--line:#e2e4e7;--soft:#eef0f2;
  --accent:#2f5fa7;--good:#1a7a4c;--good-bg:#e3f3ea;--bad:#b23a30;--bad-bg:#fbe7e4;
  --neutral-bg:#eceef1;--warn:#8a5a00;--warn-bg:#fbf0d9;--zero:#8b929c;
  --h0:#f4f6f9;--h1:#d3e0f1;--h2:#9dbbe2;--h3:#5a8ccb;--h4:#21508f;
  --h0t:#2a3240;--h1t:#1f2b3d;--h2t:#14213a;--h3t:#ffffff;--h4t:#ffffff;
}
@media (prefers-color-scheme: dark){:root{
  --bg:#15171a;--surface:#1d2024;--fg:#e6e8eb;--muted:#9aa2ad;--line:#30343a;--soft:#262a2f;
  --accent:#7fa8e6;--good:#5cc890;--good-bg:#173527;--bad:#f08a80;--bad-bg:#3d1f1c;
  --neutral-bg:#2a2e34;--warn:#e8b85c;--warn-bg:#3a2e14;--zero:#7a828d;
  --h0:#20252c;--h1:#233a5a;--h2:#2f5e98;--h3:#5b93d6;--h4:#a9cdf6;
  --h0t:#c9d0da;--h1t:#dbe5f3;--h2t:#ffffff;--h3t:#0d1520;--h4t:#0d1520;
}}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--fg);
  font:15px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif;
  font-variant-numeric:tabular-nums}
main{max-width:1080px;margin:0 auto;padding:24px 16px 48px}
h1{font-size:1.5rem;margin:0 0 4px;overflow-wrap:anywhere}
h2{font-size:1.1rem;margin:36px 0 10px}
p{margin:6px 0}
.muted{color:var(--muted)}
.small{font-size:.85rem}
.meta{display:flex;flex-wrap:wrap;gap:6px 18px;color:var(--muted);font-size:.9rem;margin:0}
.meta b{color:var(--fg);font-weight:600}
.cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(250px,1fr));gap:12px}
.card{background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:14px 16px;
  min-width:0}
.card h3{margin:0 0 6px;font-size:.95rem;font-weight:600;overflow-wrap:anywhere}
.big{font-size:1.6rem;font-weight:650;letter-spacing:-.01em}
.pill{display:inline-block;border-radius:999px;padding:1px 10px;font-size:.8rem;font-weight:600;
  background:var(--neutral-bg);color:var(--fg)}
.pill.better{background:var(--good-bg);color:var(--good)}
.pill.worse{background:var(--bad-bg);color:var(--bad)}
.pill.insufficient{background:var(--warn-bg);color:var(--warn)}
.kv{display:grid;grid-template-columns:auto 1fr;gap:2px 12px;font-size:.85rem;margin-top:8px}
.kv dt{color:var(--muted)}
.kv dd{margin:0;text-align:right}
.scroll{overflow-x:auto;-webkit-overflow-scrolling:touch;max-width:100%;
  border:1px solid var(--line);border-radius:10px;background:var(--surface)}
table{border-collapse:collapse;width:100%;font-size:.88rem}
th,td{padding:7px 10px;text-align:right;white-space:nowrap;border-bottom:1px solid var(--line)}
th{font-weight:600;color:var(--muted);background:var(--soft)}
th:first-child,td:first-child{text-align:left}
tr:last-child td{border-bottom:0}
td.name{max-width:22ch;overflow:hidden;text-overflow:ellipsis}
.badge{font-size:.72rem;color:var(--muted);border:1px solid var(--line);border-radius:4px;
  padding:0 4px;margin-left:6px;vertical-align:1px}
figure{margin:0;background:var(--surface);border:1px solid var(--line);border-radius:10px;
  padding:12px}
figcaption{font-size:.85rem;color:var(--muted);margin-top:6px}
svg{display:block;width:100%;height:auto;max-width:760px;margin:0 auto}
svg text{fill:var(--fg);font-family:inherit;font-size:12px}
svg .muted{fill:var(--muted)}
svg .grid{stroke:var(--line);stroke-width:1}
svg .zero{stroke:var(--zero);stroke-width:1.2;stroke-dasharray:4 3}
svg .axis{stroke:var(--muted);stroke-width:1}
svg .whisker{stroke:var(--fg);stroke-width:1.6}
svg .pt{fill:var(--accent)}
svg .pt.better{fill:var(--good)}
svg .pt.worse{fill:var(--bad)}
svg .pt.base{fill:var(--surface);stroke:var(--fg);stroke-width:1.6}
svg .frontier{fill:none;stroke:var(--accent);stroke-width:1.2;stroke-dasharray:5 4;opacity:.7}
table.heat td,table.heat th{text-align:center;padding:5px 8px}
table.heat td:first-child,table.heat th:first-child{text-align:left;position:sticky;left:0;
  background:var(--surface);z-index:1}
table.heat th:first-child{background:var(--soft)}
table.heat td.c{min-width:64px;font-size:.8rem;border:2px solid var(--surface)}
.h0{background:var(--h0);color:var(--h0t)}.h1{background:var(--h1);color:var(--h1t)}
.h2{background:var(--h2);color:var(--h2t)}.h3{background:var(--h3);color:var(--h3t)}
.h4{background:var(--h4);color:var(--h4t)}
.na{background:repeating-linear-gradient(45deg,var(--soft) 0 4px,var(--surface) 4px 8px);
  color:var(--muted)}
.legend{display:flex;flex-wrap:wrap;gap:6px 14px;font-size:.8rem;color:var(--muted);margin:8px 0}
.legend span{display:inline-flex;align-items:center;gap:6px}
.legend i{display:inline-block;width:18px;height:12px;border-radius:3px;
  border:1px solid var(--line)}
details{margin-top:12px}
summary{cursor:pointer;color:var(--accent);font-size:.9rem;margin-bottom:8px}
.chips{display:flex;flex-wrap:wrap;gap:6px;padding:0;margin:0;list-style:none}
.chips li{background:var(--surface);border:1px solid var(--line);border-radius:6px;padding:1px 8px;
  font-size:.82rem;overflow-wrap:anywhere}
ul.notes{padding-left:20px;margin:0}
ul.notes li{margin:4px 0}
footer{margin-top:40px;padding-top:16px;border-top:1px solid var(--line);font-size:.85rem;
  color:var(--muted)}
footer p{margin:8px 0;max-width:75ch}
code{font-family:ui-monospace,SFMono-Regular,Consolas,Menlo,monospace;font-size:.9em}
""".strip()


def _e(s: Any) -> str:
    return html.escape(str(s), quote=True)


def _fmt_num(v: float) -> str:
    """Compact SVG coordinate."""
    return f"{v:.1f}".rstrip("0").rstrip(".")


def _nice_step(span: float, target: int = 6) -> float:
    raw = span / max(target, 1)
    mag = 10 ** math.floor(math.log10(raw)) if raw > 0 else 1
    for m in (1, 2, 2.5, 5, 10):
        if m * mag >= raw:
            return m * mag
    return 10 * mag


def _ticks(lo: float, hi: float, target: int = 6) -> list[float]:
    step = _nice_step(hi - lo, target)
    start = math.ceil(lo / step - 1e-9) * step
    out = []
    v = start
    while v <= hi + 1e-9:
        out.append(round(v, 10))
        v += step
    return out


def _svg_trunc(s: str, n: int) -> str:
    return s if len(s) <= n else s[: n - 1] + "…"


def _verdict_class(verdict: str) -> str:
    return {"better": "better", "worse": "worse", "insufficient data": "insufficient"}.get(
        verdict, "neutral")


def _forest_svg(a: Analysis) -> str:
    comps = a.comparisons
    width, left, right_pad, row_h, top = 600, 150, 150, 32, 12
    x0, x1 = left, width - right_pad
    vals = [0.0]
    for c in comps:
        for v in (c.pass_rate_diff.estimate, c.pass_rate_diff.low, c.pass_rate_diff.high):
            if _num(v) is not None:
                vals.append(v * 100)
    lo, hi = min(vals), max(vals)
    pad = max((hi - lo) * 0.08, 1.0)
    lo, hi = lo - pad, hi + pad
    if hi - lo < 10:
        mid = (hi + lo) / 2
        lo, hi = mid - 5, mid + 5
    ticks = _ticks(lo, hi)
    lo, hi = min(lo, ticks[0]), max(hi, ticks[-1])

    def sx(v: float) -> float:
        return x0 + (v - lo) / (hi - lo) * (x1 - x0)

    plot_h = row_h * len(comps)
    axis_y = top + plot_h + 4
    height = axis_y + 44
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" role="img" '
             f'aria-label="Forest plot of pass-rate difference versus {_e(a.baseline)}">']
    for t in ticks:
        x = _fmt_num(sx(t))
        parts.append(f'<line class="grid" x1="{x}" y1="{top}" x2="{x}" y2="{axis_y}"/>')
        label = f"{t:+g}" if t else "0"
        parts.append(f'<text class="muted" x="{x}" y="{axis_y + 16}" text-anchor="middle">'
                     f"{_e(label)}</text>")
    zx = _fmt_num(sx(0))
    parts.append(f'<line class="zero" x1="{zx}" y1="{top - 4}" x2="{zx}" y2="{axis_y}"/>')
    parts.append(f'<line class="axis" x1="{x0}" y1="{axis_y}" x2="{x1}" y2="{axis_y}"/>')
    parts.append(f'<text class="muted" x="{_fmt_num((x0 + x1) / 2)}" y="{axis_y + 36}" '
                 f'text-anchor="middle">Pass-rate difference vs '
                 f"{_e(_svg_trunc(a.baseline, 24))} (percentage points)</text>")
    for i, c in enumerate(comps):
        cy = top + row_h * i + row_h / 2
        y = _fmt_num(cy)
        parts.append(f'<text x="{left - 10}" y="{_fmt_num(cy + 4)}" text-anchor="end">'
                     f"<title>{_e(c.arm)}</title>{_e(_svg_trunc(c.arm, 20))}</text>")
        iv = c.pass_rate_diff
        est, low, high = _num(iv.estimate), _num(iv.low), _num(iv.high)
        if low is not None and high is not None:
            xa, xb = _fmt_num(sx(low * 100)), _fmt_num(sx(high * 100))
            parts.append(f'<line class="whisker" x1="{xa}" y1="{y}" x2="{xb}" y2="{y}"/>')
            for xe in (xa, xb):
                parts.append(f'<line class="whisker" x1="{xe}" y1="{_fmt_num(cy - 5)}" '
                             f'x2="{xe}" y2="{_fmt_num(cy + 5)}"/>')
        if est is not None:
            cls = _verdict_class(c.verdict)
            parts.append(f'<circle class="pt {cls}" cx="{_fmt_num(sx(est * 100))}" cy="{y}" r="5">'
                         f"<title>{_e(c.arm)}: {_e(fmt_pts(est))} {_e(_pts_ci(iv))}</title>"
                         "</circle>")
            value = f"{fmt_pts(est, unit=False)} {_pts_ci(iv)}".strip()
        else:
            value = "no paired data"
        parts.append(f'<text class="muted" x="{x1 + 10}" y="{_fmt_num(cy + 4)}">{_e(value)}</text>')
    parts.append("</svg>")
    return "".join(parts)


def _scatter_svg(a: Analysis, arms: list[ArmSummary]) -> str:
    width, height = 600, 380
    ml, mr, mt, mb = 64, 130, 16, 50
    x0, x1, y0, y1 = ml, width - mr, mt, height - mb
    xs = [0.0]
    for s in arms:
        for v in (s.mean_cost_usd.estimate, s.mean_cost_usd.high):
            if _num(v) is not None:
                xs.append(v)
    xmax = max(xs) * 1.08 or 1.0
    xticks = _ticks(0, xmax, 5)
    xmax = max(xmax, xticks[-1])

    def sx(v: float) -> float:
        return x0 + v / xmax * (x1 - x0)

    def sy(v: float) -> float:
        return y1 - v * (y1 - y0)

    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" role="img" '
             'aria-label="Mean cost per trial versus pass rate for each arm">']
    for t in (0, 0.2, 0.4, 0.6, 0.8, 1.0):
        y = _fmt_num(sy(t))
        parts.append(f'<line class="grid" x1="{x0}" y1="{y}" x2="{x1}" y2="{y}"/>')
        parts.append(f'<text class="muted" x="{x0 - 8}" y="{_fmt_num(sy(t) + 4)}" '
                     f'text-anchor="end">{t * 100:.0f}%</text>')
    for t in xticks:
        x = _fmt_num(sx(t))
        parts.append(f'<line class="grid" x1="{x}" y1="{y0}" x2="{x}" y2="{y1}"/>')
        parts.append(f'<text class="muted" x="{x}" y="{y1 + 16}" text-anchor="middle">'
                     f"{_e(fmt_cost(t))}</text>")
    parts.append(f'<line class="axis" x1="{x0}" y1="{y1}" x2="{x1}" y2="{y1}"/>')
    parts.append(f'<line class="axis" x1="{x0}" y1="{y0}" x2="{x0}" y2="{y1}"/>')
    parts.append(f'<text class="muted" x="{_fmt_num((x0 + x1) / 2)}" y="{height - 10}" '
                 'text-anchor="middle">Mean cost per trial (USD)</text>')
    parts.append(f'<text class="muted" transform="translate(16 {_fmt_num((y0 + y1) / 2)}) '
                 'rotate(-90)" text-anchor="middle">Pass rate</text>')

    pts = [(s, s.mean_cost_usd.estimate, s.pass_rate.estimate) for s in arms
           if _num(s.mean_cost_usd.estimate) is not None and _num(s.pass_rate.estimate) is not None]
    # Pareto frontier: arms no other arm beats on both cost (lower) and pass rate (higher).
    frontier = [p for p in pts if not any(
        q is not p and q[1] <= p[1] and q[2] >= p[2] and (q[1] < p[1] or q[2] > p[2]) for q in pts)]
    frontier.sort(key=lambda p: p[1])
    if len(frontier) > 1:
        coords = " ".join(f"{_fmt_num(sx(c))},{_fmt_num(sy(r))}" for _, c, r in frontier)
        parts.append(f'<polyline class="frontier" points="{coords}"/>')

    for s, cost, rate in pts:
        cx, cy = sx(cost), sy(rate)
        cl, ch = _num(s.mean_cost_usd.low), _num(s.mean_cost_usd.high)
        if cl is not None and ch is not None:
            parts.append(f'<line class="whisker" x1="{_fmt_num(sx(cl))}" y1="{_fmt_num(cy)}" '
                         f'x2="{_fmt_num(sx(ch))}" y2="{_fmt_num(cy)}"/>')
        rl, rh = _num(s.pass_rate.low), _num(s.pass_rate.high)
        if rl is not None and rh is not None:
            parts.append(f'<line class="whisker" x1="{_fmt_num(cx)}" y1="{_fmt_num(sy(rl))}" '
                         f'x2="{_fmt_num(cx)}" y2="{_fmt_num(sy(rh))}"/>')
    # Labels: nudge apart vertically so neighbouring arms stay readable.
    placed: list[float] = []
    for s, cost, rate in sorted(pts, key=lambda p: -p[2]):
        cx, cy = sx(cost), sy(rate)
        ly = cy - 8
        for py in sorted(placed):
            if abs(ly - py) < 14:
                ly = py + 14
        placed.append(ly)
        base = s.arm == a.baseline
        shape = (f'<rect class="pt base" x="{_fmt_num(cx - 5)}" y="{_fmt_num(cy - 5)}" '
                 'width="10" height="10"' if base else
                 f'<circle class="pt" cx="{_fmt_num(cx)}" cy="{_fmt_num(cy)}" r="5"')
        tip = f"{s.arm}: {fmt_pct(rate)}, {fmt_cost(cost)} per trial"
        parts.append(f"{shape}><title>{_e(tip)}</title></{'rect' if base else 'circle'}>")
        label = _svg_trunc(s.arm, 18) + (" (baseline)" if base else "")
        # ~6.6 units per character at 12px; flip to the left side when the label would clip.
        if cx + 9 + len(label) * 6.6 > width:
            parts.append(f'<text x="{_fmt_num(cx - 9)}" y="{_fmt_num(ly)}" text-anchor="end">'
                         f"{_e(label)}</text>")
        else:
            parts.append(f'<text x="{_fmt_num(cx + 9)}" y="{_fmt_num(ly)}">{_e(label)}</text>')
    parts.append("</svg>")
    return "".join(parts)


def _heat_class(c: TaskCell | None) -> str:
    f = _frac(c)
    if f is None:
        return "na"
    if f <= 0:
        return "h0"
    if f >= 1:
        return "h4"
    if f <= 1 / 3:
        return "h1"
    return "h2" if f < 2 / 3 else "h3"


def _heat_table(
    tasks: list[str], arms: list[str], lookup: dict[tuple[str, str], TaskCell]
) -> str:
    head = "".join(f"<th>{_e(x)}</th>" for x in arms)
    rows = []
    for t in tasks:
        cells = []
        for arm in arms:
            c = lookup.get((t, arm))
            if c is None:
                tip = f"{t} / {arm}: no trials"
            else:
                tip = (f"{t} / {arm}: {c.passes} of {c.trials} completed trials passed"
                       + (f", {c.errors} infrastructure error(s)" if c.errors else ""))
            cells.append(f'<td class="c {_heat_class(c)}" title="{_e(tip)}">'
                         f"{_e(_cell_label(c))}</td>")
        rows.append(f'<tr><td class="name" title="{_e(t)}">{_e(t)}</td>{"".join(cells)}</tr>')
    return (f'<div class="scroll"><table class="heat"><thead><tr><th>Task</th>{head}</tr></thead>'
            f'<tbody>{"".join(rows)}</tbody></table></div>')


_LEGEND = (
    '<div class="legend" aria-label="Heatmap legend">'
    '<span><i class="h0"></i>none passed</span>'
    '<span><i class="h1"></i>up to 1/3</span>'
    '<span><i class="h2"></i>1/3 to 2/3</span>'
    '<span><i class="h3"></i>2/3 or more</span>'
    '<span><i class="h4"></i>all passed</span>'
    '<span><i class="na"></i>no completed trials</span>'
    "</div>"
)


def _card(a: Analysis, c: Comparison) -> str:
    level = _ci_level(a.alpha)
    cls = _verdict_class(c.verdict)
    verdict = _VERDICT_SHORT.get(c.verdict, str(c.verdict))
    iv = c.pass_rate_diff
    has_ci = _num(iv.low) is not None and _num(iv.high) is not None
    ci_text = (f"{fmt_pts(iv.low, unit=False)} to {fmt_pts(iv.high, unit=False)} pts"
               if has_ci else "not available")
    if c.verdict == "insufficient data":
        n = c.paired_tasks
        expl = (f"Only {n} task{'' if n == 1 else 's'} completed in both arms; at least 2 are "
                "needed for a comparison.")
    elif c.verdict == "no detectable difference":
        if has_ci and iv.low < iv.high and iv.low <= 0 <= iv.high:
            expl = f"The data are consistent with a true difference anywhere from {ci_text}."
        else:
            # A zero-width interval, one that excludes 0, or none at all: quoting it as the
            # range of plausible differences would contradict the verdict.
            expl = (f"Holm-adjusted p = {fmt_p(c.p_value_adjusted)} is not below alpha "
                    f"{a.alpha:g}. With few or uniform tasks the bootstrap interval "
                    "understates uncertainty.")
    else:
        expl = (f"Holm-adjusted p = {fmt_p(c.p_value_adjusted)} is below alpha {a.alpha:g} and "
                f"the {level} ({ci_text}) excludes zero.")
    kv = [
        (level, ci_text),
        ("p / Holm", f"{fmt_p(c.p_value)} / {fmt_p(c.p_value_adjusted)}"),
        ("Cost ratio", _ratio_ci(c.cost_ratio)),
        ("Time ratio", _ratio_ci(c.duration_ratio)),
        ("Paired tasks", f"{c.paired_tasks} ({c.tasks_better} better, {c.tasks_worse} worse, "
                         f"{c.tasks_tied} tied)"),
    ]
    dl = "".join(f"<dt>{_e(k)}</dt><dd>{_e(v)}</dd>" for k, v in kv)
    return (
        f'<div class="card"><h3>{_e(c.arm)} <span class="muted">vs {_e(c.baseline)}</span></h3>'
        f'<div class="big">{_e(fmt_pts(iv.estimate))}</div>'
        f'<span class="pill {cls}">{_e(verdict)}</span>'
        f'<p class="small muted">{_e(expl)}</p><dl class="kv">{dl}</dl></div>'
    )


def _arm_table(a: Analysis) -> str:
    level = _ci_level(a.alpha)
    heads = ["Arm", "Pass rate", level, "Tasks", "Trials", "Errors", "Cost / trial",
             "Cost / pass", "Time / trial", "Tokens in / out", "Turns"]
    rows = []
    for s in a.arms:
        badge = '<span class="badge">baseline</span>' if s.arm == a.baseline else ""
        vals = [fmt_pct(s.pass_rate.estimate), _pct_ci(s.pass_rate), str(s.tasks), str(s.trials),
                str(s.errors), fmt_cost(s.mean_cost_usd.estimate), fmt_cost(s.cost_per_pass_usd),
                fmt_duration(s.mean_duration_s.estimate), _tokens(s), fmt_count(s.mean_turns)]
        tds = "".join(f"<td>{_e(v)}</td>" for v in vals)
        rows.append(f'<tr><td class="name" title="{_e(s.arm)}">{_e(s.arm)}{badge}</td>{tds}</tr>')
    th = "".join(f"<th>{_e(h)}</th>" for h in heads)
    return (f'<div class="scroll"><table><thead><tr>{th}</tr></thead>'
            f'<tbody>{"".join(rows)}</tbody></table></div>')


def _section(sid: str, title: str, body: str) -> str:
    return f'<section id="{sid}"><h2>{_e(title)}</h2>{body}</section>'


def _chips(items: Iterable[str]) -> str:
    return '<ul class="chips">' + "".join(f"<li>{_e(t)}</li>" for t in items) + "</ul>"


def render_html(a: Analysis, *, title: str | None = None) -> str:
    """Single self-contained HTML page (inline CSS and SVG, no scripts or external resources)."""
    page_title = title or f"{a.experiment} - agent-ab report"
    level = _ci_level(a.alpha)
    n_tasks = len(_task_order(a))
    meta = [
        ("Baseline", a.baseline),
        ("Tasks", str(n_tasks)),
        ("Trials", f"{a.completed_trials} / {a.planned_trials} completed"),
        ("Infrastructure errors", str(a.error_trials)),
        ("Total cost", fmt_cost(a.total_cost_usd)),
        ("Alpha", f"{a.alpha:g}"),
    ]
    body: list[str] = [
        f"<header><h1>{_e(a.experiment)}</h1>",
        '<p class="meta">' + "".join(f"<span>{_e(k)} <b>{_e(v)}</b></span>" for k, v in meta)
        + "</p></header>",
    ]

    if a.comparisons:
        cards = '<div class="cards">' + "".join(_card(a, c) for c in a.comparisons) + "</div>"
    else:
        cards = '<p class="muted">Only one arm was analysed, so there is nothing to compare.</p>'
    body.append(_section("verdicts", f"Pass rate vs {a.baseline}", cards))

    body.append(_section("arms", "Arms", _arm_table(a)
                         + '<p class="small muted">Pass rate is the mean over tasks of each '
                         "task's pass fraction. Costs and times are per completed trial.</p>"))

    if a.comparisons:
        fig = (f"<figure>{_forest_svg(a)}<figcaption>Dots: estimated difference in pass rate "
               f"against {_e(a.baseline)}; whiskers: {_e(level)}. Intervals that cross the dashed "
               "zero line are consistent with no difference.</figcaption></figure>")
        body.append(_section("forest", "Difference in pass rate", fig))

    with_cost = [s for s in a.arms if _num(s.mean_cost_usd.estimate) is not None
                 and _num(s.pass_rate.estimate) is not None]
    if with_cost:
        missing = [s.arm for s in a.arms if s not in with_cost]
        cap = (f"Each arm's mean cost per trial against its pass rate; whiskers show {_e(level)}s "
               "on both axes. Up and to the left is better; the dashed line joins arms that no "
               "other arm beats on both cost and pass rate.")
        if missing:
            cap += (" Not shown (no cost or pass-rate data): "
                    + ", ".join(_e(m) for m in missing) + ".")
        fig = f"<figure>{_scatter_svg(a, with_cost)}<figcaption>{cap}</figcaption></figure>"
    else:
        fig = '<p class="muted">No arm reported cost, so the cost chart is omitted.</p>'
    body.append(_section("cost", "Cost vs pass rate", fig))

    disagree, agree, lookup = _split_tasks(a)
    arms = _arm_order(a)
    if n_tasks == 0:
        heat = '<p class="muted">No task results.</p>'
    else:
        intro = ('<p class="small muted">Each cell shows passes / completed trials for one task '
                 'and arm ("+1 err" marks infrastructure errors, excluded from the count). Tasks '
                 "where arms disagree come first.</p>")
        heat = intro + _LEGEND
        if n_tasks <= HEATMAP_FULL_LIMIT:
            heat += _heat_table(disagree + agree, arms, lookup)
        else:
            if disagree:
                heat += (f'<p class="small">{len(disagree)} of {n_tasks} tasks have different '
                         "results across arms.</p>" + _heat_table(disagree, arms, lookup))
            else:
                heat += (f'<p class="small">All {n_tasks} tasks have the same result in every '
                         "arm.</p>")
            if agree:
                heat += (f"<details><summary>{len(agree)} tasks with the same result in every arm"
                         f"</summary>{_heat_table(agree, arms, lookup)}</details>")
    body.append(_section("tasks", "Results by task", heat))

    if a.flaky_tasks:
        shown = a.flaky_tasks[:FLAKY_INLINE_LIMIT]
        flaky = ('<p class="small muted">Outcome varied across repeats within at least one arm. '
                 "These tasks add noise; more repeats narrow their uncertainty.</p>"
                 + _chips(shown))
        if len(a.flaky_tasks) > len(shown):
            rest = a.flaky_tasks[len(shown):]
            flaky += f"<details><summary>{len(rest)} more</summary>{_chips(rest)}</details>"
        body.append(_section("flaky", f"Flaky tasks ({len(a.flaky_tasks)})", flaky))

    if a.notes:
        notes = '<ul class="notes">' + "".join(f"<li>{_e(n)}</li>" for n in a.notes) + "</ul>"
        body.append(_section("notes", "Notes", notes))

    body.append(
        "<footer><p><b>How to read this.</b> Every task is run under every arm, so arms are "
        "compared task by task. A task's pass fraction is the share of its completed trials "
        "whose hidden check passed; infrastructure errors are excluded.</p>"
        f"<p><b>{_e(level)} (task-level bootstrap).</b> Tasks are resampled with replacement "
        "thousands of times and the "
        "statistic is recomputed each time; the interval holds the middle "
        f"{_e(level.split()[0])} of those results. Resampling whole tasks (not single trials) "
        "keeps repeats of the same task together, so the interval reflects how much results "
        "depend on which tasks happened to be in the suite.</p>"
        "<p><b>p-value.</b> A paired sign-flip test: if an arm made no difference, each task's "
        "difference would be equally likely to be positive or negative. The p-value is how often "
        "randomly flipping those signs gives a mean difference at least as large as the observed "
        "one. With several arms, p-values are Holm-adjusted so that the chance of any false "
        "alarm across all comparisons stays below alpha.</p>"
        "<p><b>Verdicts.</b> An arm gets “higher pass rate” or “lower pass rate” only when the "
        "adjusted p-value is "
        "below alpha and the interval excludes zero. “No detectable difference” is not "
        "proof of equality: the interval shows the range of differences the data cannot rule "
        "out.</p><p>Generated by agent-ab.</p></footer>"
    )

    return (
        "<!DOCTYPE html>\n"
        '<html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        '<meta name="color-scheme" content="light dark">'
        f"<title>{_e(page_title)}</title><style>{_CSS}</style></head>"
        f"<body><main>{''.join(body)}</main></body></html>\n"
    )
