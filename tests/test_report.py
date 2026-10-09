"""Tests for the report renderers, using hand-built ``Analysis`` objects."""

from __future__ import annotations

import json
import math
import re
from html.parser import HTMLParser

import pytest

from agent_ab.model import Analysis, ArmSummary, Comparison, Interval, TaskCell
from agent_ab.report import (
    fmt_cost,
    fmt_duration,
    fmt_pct,
    fmt_pts,
    render_html,
    render_json,
    render_markdown,
    render_text,
)

NONE = Interval(None, None, None)


def arm(name, rate, *, cost=0.05, dur=41.2, trials=30, errors=0, tasks=10):
    has_cost = cost is not None
    rate_iv = Interval(rate, max(rate - 0.12, 0), min(rate + 0.12, 1)) if rate is not None else NONE
    return ArmSummary(
        arm=name, trials=trials, errors=errors, passes=round((rate or 0) * trials), tasks=tasks,
        pass_rate=rate_iv, pass_rate_wilson=rate_iv,
        mean_cost_usd=Interval(cost, cost * 0.9, cost * 1.1) if has_cost else NONE,
        total_cost_usd=cost * trials if has_cost else None,
        mean_duration_s=Interval(dur, dur * 0.9, dur * 1.1) if dur is not None else NONE,
        mean_input_tokens=12345.0 if has_cost else None,
        mean_output_tokens=2100.0 if has_cost else None,
        mean_turns=7.5 if has_cost else None,
        cost_per_pass_usd=(
            cost * trials / max(round(rate * trials), 1) if has_cost and rate else None
        ),
    )


def comp(name, base, diff, lo, hi, p, padj, verdict, *, paired=10, cost=(0.91, 0.80, 1.03)):
    return Comparison(
        arm=name, baseline=base, paired_tasks=paired,
        pass_rate_diff=Interval(diff, lo, hi), p_value=p, p_value_adjusted=padj,
        cost_ratio=Interval(*cost) if cost else NONE,
        duration_ratio=Interval(1.05, 0.95, 1.2), tasks_better=3, tasks_worse=1,
        tasks_tied=paired - 4 if paired >= 4 else 0, verdict=verdict,
    )


def cells(task_ids, arms, fn):
    out = []
    for i, t in enumerate(task_ids):
        for j, a in enumerate(arms):
            trials, passes, errors = fn(i, j)
            out.append(TaskCell(t, a, trials, passes, errors, 0.05 if trials else None,
                                40.0 if trials else None))
    return out


def analysis_typical() -> Analysis:
    tasks = [f"task-{i:02d}" for i in range(10)]
    return Analysis(
        experiment="tests-vs-no-tests", baseline="control", alpha=0.05,
        arms=[arm("control", 0.6), arm("no-tests", 0.642, cost=0.0455)],
        comparisons=[comp("no-tests", "control", 0.042, -0.061, 0.145, 0.41, 0.41,
                          "no detectable difference")],
        cells=cells(tasks, ["control", "no-tests"], lambda i, j: (3, (i + j) % 4, 0)),
        flaky_tasks=["task-01", "task-02"], planned_trials=60, completed_trials=60,
        error_trials=0, total_cost_usd=2.865,
        notes=["no-tests vs control: only 10 paired tasks. Intervals from few tasks tend to be "
               "too narrow."],
    )


def analysis_four_arms() -> Analysis:
    names = ["control", "opus", "no-cost", "broken"]
    tasks = [f"t{i}" for i in range(12)]

    def fn(i, j):
        if j == 3:
            return (0, 0, 3)
        return (3, (i * (j + 1)) % 4, 1 if (i == 2 and j == 1) else 0)

    return Analysis(
        experiment="four-arm", baseline="control", alpha=0.05,
        arms=[arm("control", 0.5), arm("opus", 0.75, cost=1.37, dur=185.0),
              arm("no-cost", 0.55, cost=None), arm("broken", None, cost=None, dur=None,
                                                    trials=0, errors=36, tasks=0)],
        comparisons=[
            comp("opus", "control", 0.25, 0.1, 0.4, 0.002, 0.006, "better", cost=(27.4, 20, 35)),
            comp("no-cost", "control", 0.05, -0.1, 0.2, 0.5, 1.0, "no detectable difference",
                 cost=None),
            Comparison("broken", "control", 0, NONE, None, None, NONE, NONE, 0, 0, 0,
                       "insufficient data"),
        ],
        cells=cells(tasks, names, fn), flaky_tasks=["t1"], planned_trials=144,
        completed_trials=107, error_trials=37, total_cost_usd=float("nan"),
        notes=["37 trials excluded as infrastructure errors", "cost not reported for arm no-cost"],
    )


def analysis_one_task() -> Analysis:
    return Analysis(
        experiment="tiny", baseline="a", alpha=0.05,
        arms=[arm("a", 1.0, trials=1, tasks=1), arm("b", 0.0, trials=1, tasks=1)],
        comparisons=[Comparison("b", "a", 1, Interval(-1.0, None, None), None, None,
                                Interval(1.0, None, None), NONE, 0, 1, 0, "insufficient data")],
        cells=[TaskCell("only", "a", 1, 1, 0, 0.05, 3.0),
               TaskCell("only", "b", 1, 0, 0, None, None)],
        flaky_tasks=[], planned_trials=2, completed_trials=2, error_trials=0,
        total_cost_usd=0.05, notes=["b vs a: 1 paired task(s); at least 2 are needed to compare."],
    )


def analysis_many_tasks(n: int = 300) -> Analysis:
    tasks = [f"task-{i:03d}" for i in range(n)]
    a = analysis_typical()
    a.experiment = "big-suite"
    a.cells = cells(tasks, ["control", "no-tests"],
                    lambda i, j: (3, 3 if i % 5 else j * 3, 0))
    a.flaky_tasks = tasks[:120]
    a.planned_trials = a.completed_trials = n * 6
    return a


HOSTILE = '<script>alert("x")</script>'


def analysis_hostile() -> Analysis:
    bad_arm = HOSTILE + " & 'q' | *b* `c`"
    bad_task = '"><img src=x onerror=alert(1)>'
    return Analysis(
        experiment=HOSTILE, baseline="ctl</title>", alpha=0.05,
        arms=[arm("ctl</title>", 0.5), arm(bad_arm, 0.4)],
        comparisons=[comp(bad_arm, "ctl</title>", -0.1, -0.3, 0.1, 0.3, 0.3,
                          "no detectable difference")],
        cells=cells([bad_task, "ok"], ["ctl</title>", bad_arm], lambda i, j: (2, i + j, 0)),
        flaky_tasks=[bad_task], planned_trials=8, completed_trials=8, error_trials=0,
        total_cost_usd=0.4, notes=[HOSTILE + " note é—✓"],
    )


CASES = {
    "typical": analysis_typical,
    "four": analysis_four_arms,
    "one": analysis_one_task,
    "many": analysis_many_tasks,
    "hostile": analysis_hostile,
}


# --------------------------------------------------------------------------- formatting


def test_formatters():
    assert fmt_pct(0.417) == "41.7%"
    assert fmt_pct(None) == "-" and fmt_pct(float("nan")) == "-"
    assert fmt_pts(0.042) == "+4.2 pts" and fmt_pts(-0.061, unit=False) == "-6.1"
    assert fmt_pts(-0.0001) == "0.0 pts"
    assert fmt_cost(0.0123) == "$0.0123" and fmt_cost(1.234) == "$1.23"
    assert fmt_cost(0.312) == "$0.312" and fmt_cost(None) == "-" and fmt_cost(0) == "$0.00"
    assert fmt_duration(41.24) == "41.2s" and fmt_duration(185) == "3m 05s"
    assert fmt_duration(3720) == "1h 02m" and fmt_duration(None) == "-"


# --------------------------------------------------------------------------- text


@pytest.mark.parametrize("case", CASES)
@pytest.mark.parametrize("width", [100, 60, 40])
def test_text_ascii_and_width(case, width):
    out = render_text(CASES[case](), width=width)
    assert out.isascii()
    assert all(len(line) <= width for line in out.splitlines()), out


def test_text_headline_typical():
    out = render_text(analysis_typical(), width=200)
    assert ("no-tests vs control: +4.2 pts [-6.1, +14.5], p=0.41 (Holm 0.41) "
            "-> no detectable difference; cost x0.91 [0.80, 1.03]") in out
    assert "control *" in out and "60.0%" in out and "$0.0500" in out and "41.2s" in out
    assert "only 10 paired tasks" in out and "task-01" in out


def test_text_four_arms_none_values():
    out = render_text(analysis_four_arms())
    assert "-> higher pass rate" in out
    assert "insufficient data (0 paired tasks)" in out
    assert "total cost -" in out
    assert "broken vs control: -, p=- (Holm -)" in out
    broken = next(ln for ln in out.splitlines()
                  if ln.strip().startswith("broken ") and " vs " not in ln)
    assert " - " in broken
    assert "3m 05s" in out


def test_text_one_task_and_single_arm():
    out = render_text(analysis_one_task())
    assert "insufficient data (1 paired task)" in out
    a = analysis_one_task()
    a.comparisons = []
    assert "single arm" in render_text(a)


def test_text_many_flaky_truncated():
    out = render_text(analysis_many_tasks())
    assert "and 80 more" in out


# --------------------------------------------------------------------------- markdown


@pytest.mark.parametrize("case", CASES)
def test_markdown_tables(case):
    a = CASES[case]()
    out = render_markdown(a)
    assert out.startswith("# agent-ab report: ")
    for block in re.findall(r"(?:^\|.*\|\n)+", out, flags=re.M):
        rows = block.strip("\n").split("\n")
        counts = {len(re.split(r"(?<!\\)\|", r)) for r in rows}
        assert len(counts) == 1, block  # every row has the same number of cells
    assert "## Arms" in out


def test_markdown_content():
    out = render_markdown(analysis_typical())
    assert "| no-tests | +4.2 pts | [-6.1, +14.5] | 0.41 | 0.41 | no detectable difference" in out
    assert "control (baseline)" in out
    out4 = render_markdown(analysis_four_arms())
    assert "**higher pass rate**" in out4 and "insufficient data" in out4


def test_markdown_escapes_hostile():
    out = render_markdown(analysis_hostile())
    stripped = re.sub(r"</?(details|summary|sub)>", "", out)
    assert not re.search(r"(?<!\\)<", stripped), "unescaped < in Markdown"
    assert "\\<script\\>" in out and "\\| \\*b\\*" in out


# --------------------------------------------------------------------------- json


@pytest.mark.parametrize("case", CASES)
def test_json_round_trip(case):
    a = CASES[case]()
    out = render_json(a)
    doc = json.loads(out)
    assert doc["tool"] == "agent-ab" and doc["schema"] == 1
    assert doc["analysis"]["experiment"] == a.experiment
    assert len(doc["analysis"]["cells"]) == len(a.cells)
    assert "NaN" not in out and "Infinity" not in out
    assert out == render_json(a)  # stable
    assert list(doc) == sorted(doc)


def test_json_nan_to_null():
    doc = json.loads(render_json(analysis_four_arms()))
    assert doc["analysis"]["total_cost_usd"] is None
    a = analysis_typical()
    a.arms[0].pass_rate = Interval(float("inf"), float("-inf"), math.nan)
    doc = json.loads(render_json(a))
    assert doc["analysis"]["arms"][0]["pass_rate"] == {"estimate": None, "high": None, "low": None}


# --------------------------------------------------------------------------- html


class _Checker(HTMLParser):
    VOID = {"meta", "br", "img", "input", "link", "hr", "line", "circle", "rect", "polyline"}

    def __init__(self):
        super().__init__()
        self.stack: list[str] = []
        self.errors: list[str] = []
        self.opened: dict[str, int] = {}
        self.text: list[str] = []
        self.in_script = False

    def handle_starttag(self, tag, attrs):
        self.opened[tag] = self.opened.get(tag, 0) + 1
        if tag == "script":
            self.in_script = True
        for k, _ in attrs:
            if k.startswith("on"):
                self.errors.append(f"event handler attribute {k}")
        if tag not in self.VOID:
            self.stack.append(tag)

    def handle_startendtag(self, tag, attrs):
        self.opened[tag] = self.opened.get(tag, 0) + 1

    def handle_endtag(self, tag):
        if tag in self.VOID:
            return
        if not self.stack or self.stack[-1] != tag:
            self.errors.append(f"unexpected </{tag}>, open: {self.stack[-3:]}")
            return
        self.stack.pop()

    def handle_data(self, data):
        self.text.append(data)


def check_html(out: str) -> _Checker:
    p = _Checker()
    p.feed(out)
    p.close()
    assert not p.errors, p.errors[:5]
    assert not p.stack, p.stack
    assert "script" not in p.opened and "img" not in p.opened
    return p


@pytest.mark.parametrize("case", CASES)
def test_html_well_formed_and_self_contained(case):
    a = CASES[case]()
    out = render_html(a)
    p = check_html(out)
    for tag in ("html", "head", "body", "main", "style", "title", "table"):
        assert p.opened.get(tag, 0) >= 1, tag
    assert out.count("<section") == out.count("</section>")
    assert out.count("<svg") == out.count("</svg>")
    urls = re.findall(r"https?://[^\s\"'<>)]+", out)
    assert set(urls) <= {"http://www.w3.org/2000/svg"}, urls
    assert "@import" not in out and "url(" not in out
    assert "prefers-color-scheme: dark" in out
    assert '<meta name="viewport"' in out
    assert "bootstrap" in out and "sign-flip" in out and "Holm" in out


def test_html_typical_sections():
    out = render_html(analysis_typical())
    assert "<title>tests-vs-no-tests - agent-ab report</title>" in out
    for sid in ("verdicts", "arms", "forest", "cost", "tasks", "flaky", "notes"):
        assert f'id="{sid}"' in out
    assert "no detectable difference" in out
    assert "-6.1 to +14.5 pts" in out  # the CI is always shown with "no detectable difference"
    assert "percentage points" in out
    assert "2/3" in out and 'class="legend"' in out
    assert "<details" not in out.split('id="tasks"')[1].split("</section>")[0]
    assert render_html(analysis_typical(), title="Custom").count("<title>Custom</title>") == 1


def test_html_four_arms():
    out = render_html(analysis_four_arms())
    assert "higher pass rate" in out and "insufficient data" in out
    assert "Not shown (no cost or pass-rate data): no-cost, broken" in out
    assert ">err<" in out and "0/3 +1 err" in out and "+1e" not in out
    assert out.count('class="card"') == 3


def _card_expl(out: str) -> str:
    return re.search(r'<p class="small muted">([^<]*)</p><dl class="kv">', out).group(1)


@pytest.mark.parametrize(
    ("lo", "hi"),
    [
        (0.2, 0.6),  # CI excludes 0 but Holm p is not below alpha (e.g. 5 tasks all better)
        (-0.4, -0.1),
        (0.0, 0.0),  # zero-width: every task had the same difference
        (1.0, 1.0),
        (None, None),
    ],
)
def test_html_no_difference_card_never_contradicts(lo, hi):
    a = analysis_typical()
    a.comparisons = [comp("no-tests", "control", 0.4 if lo is None else (lo + hi) / 2, lo, hi,
                          0.0625, 0.0625, "no detectable difference", paired=5)]
    expl = _card_expl(render_html(a))
    assert "consistent with" not in expl
    assert expl == ("Holm-adjusted p = 0.062 is not below alpha 0.05. With few or uniform tasks "
                    "the bootstrap interval understates uncertainty.")


def test_html_no_difference_card_ci_spans_zero():
    expl = _card_expl(render_html(analysis_typical()))
    assert expl == "The data are consistent with a true difference anywhere from -6.1 to +14.5 pts."


def test_text_and_markdown_no_contradicting_wording():
    a = analysis_typical()
    a.comparisons = [comp("no-tests", "control", 0.0, 0.0, 0.0, 1.0, 1.0,
                          "no detectable difference")]
    for out in (render_text(a), render_markdown(a)):
        assert "no detectable difference" in out and "consistent with" not in out


def test_cell_label_errors_not_scientific():
    out = render_markdown(analysis_four_arms())
    assert "0/3 +1 err" in out and "+1e" not in out
    a = analysis_typical()
    a.cells[0] = TaskCell(a.cells[0].task, a.cells[0].arm, 3, 1, 2, 0.05, 40.0)
    html = render_html(a)
    assert "1/3 +2 err" in html and '"+1 err" marks infrastructure errors' in html


def test_html_no_cost_data():
    a = analysis_typical()
    for s in a.arms:
        s.mean_cost_usd = NONE
    out = render_html(a)
    check_html(out)
    assert "No arm reported cost" in out


def test_html_one_task():
    out = render_html(analysis_one_task())
    assert "Only 1 task completed in both arms" in out
    assert "1/1" in out and "0/1" in out


def test_html_many_tasks_collapses():
    out = render_html(analysis_many_tasks())
    tasks_sec = out.split('id="tasks"')[1].split("</section>")[0]
    assert "60 of 300 tasks have different results" in tasks_sec
    assert "<details><summary>240 tasks with the same result" in tasks_sec
    first_table = tasks_sec.split("<details>")[0]
    assert "task-000" in first_table and "task-001" not in first_table
    assert "80 more" in out


def test_html_escapes_hostile():
    out = render_html(analysis_hostile())
    p = check_html(out)
    assert "<script" not in out and "<img" not in out
    esc = "&lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt;"
    assert f"<title>{esc} - agent-ab report</title>" in out
    text = "".join(p.text)
    assert HOSTILE in text  # shown literally to the reader
    assert "✓" in out  # non-ASCII notes survive in HTML
