import json
import random
from pathlib import Path

import pytest

from agent_ab import power, stats
from agent_ab.cli import main
from agent_ab.config import load_experiment
from agent_ab.model import TrialRecord
from agent_ab.store import RunStore


def small_options(**overrides) -> power.PowerOptions:
    args = {"effect": "20", "tasks": "10,40", "repeats": "1,3", "sims": "40", "seed": "3"}
    args.update(overrides)
    return power.parse_options(**args)


# --------------------------------------------------------------------------- building blocks


def test_exact_sign_flip_matches_stats_enumeration():
    r = random.Random(7)
    cache: dict = {}
    for _ in range(200):
        reps = r.choice([1, 2, 3, 5])
        diffs = [r.randint(-reps, reps) for _ in range(r.randint(1, 20))]
        if sum(1 for d in diffs if d) > 16:
            continue
        expected = stats.sign_flip_test([d / reps for d in diffs])
        assert power.sign_flip_p_counts(diffs, reps, cache) == pytest.approx(expected, abs=1e-9)


def test_exact_sign_flip_agrees_with_monte_carlo_for_many_tasks():
    r = random.Random(11)
    diffs = [r.choice([-1, 0, 1, 1]) for _ in range(60)]
    exact = power.sign_flip_p_counts(diffs, 1)
    mc = stats.sign_flip_test([float(d) for d in diffs], n_perm=20000, rng=1)
    assert abs(exact - mc) < 0.01


def test_sign_flip_all_zero_is_one():
    assert power.sign_flip_p_counts([0, 0, 0], 3) == 1.0


def test_solve_shift_hits_the_requested_mean_difference():
    r = random.Random(1)
    probs = [power.beta_model().sample(r) for _ in range(50)]
    shift, capped = power.solve_shift(probs, 0.15)
    assert not capped and shift > 0
    arm = [1 / (1 + (1 - p) / p * pow(2.718281828459045, -shift)) for p in probs]
    assert sum(arm) / 50 - sum(probs) / 50 == pytest.approx(0.15, abs=1e-6)


def test_solve_shift_caps_when_headroom_is_too_small():
    shift, capped = power.solve_shift([0.9, 0.95, 0.99], 0.2)
    assert capped and shift == power._MAX_SHIFT


# --------------------------------------------------------------------------- options


def test_parse_options_defaults_and_dedup():
    o = power.parse_options(effect="20,10,10", tasks="50, 10", repeats="3,1,3")
    assert o.effects == (10.0, 20.0)
    assert o.tasks == (10, 50)
    assert o.repeats == (1, 3)
    assert (o.alpha, o.sims, o.seed) == (0.05, 400, 0)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"effect": "0"},
        {"effect": "-100"},
        {"effect": "10,0"},
        {"effect": "100"},
        {"effect": "abc"},
        {"effect": "10,"},
        {"tasks": "1"},
        {"tasks": "0"},
        {"tasks": "2.5"},
        {"repeats": "0"},
        {"alpha": "1"},
        {"alpha": "0"},
        {"sims": "0"},
        {"seed": "x"},
    ],
)
def test_parse_options_rejects_bad_values(kwargs):
    with pytest.raises(ValueError):
        power.parse_options(**kwargs)


# --------------------------------------------------------------------------- simulation


def test_plan_is_deterministic_for_a_seed():
    model = power.beta_model()
    a = power.render_json(power.run_plan(model, small_options()))
    b = power.render_json(power.run_plan(model, small_options()))
    assert a == b


def test_power_increases_with_tasks():
    model = power.beta_model()
    few = power.simulate_design(model, 20.0, 10, 1, alpha=0.05, sims=100, seed=0)
    many = power.simulate_design(model, 20.0, 60, 1, alpha=0.05, sims=100, seed=0)
    assert many.power > few.power + 0.3
    assert 0 <= few.se < 0.06


def test_no_effect_gives_power_at_most_alpha():
    model = power.beta_model()
    null = power.simulate_design(model, 0.0, 40, 3, alpha=0.05, sims=300, seed=0)
    assert null.power <= 0.09  # nominal 5%, loose bound for Monte Carlo error


def test_recommendation_and_text_output():
    plan = power.run_plan(power.beta_model(), small_options(effect="5,20"))
    text = power.render_text(plan)
    assert "Smallest design with at least 80% power:" in text
    assert "+5 pts: none of the simulated designs reach 80%; try more tasks." in text
    best = plan.recommendation(20.0)
    assert best is not None and best.power >= 0.8
    assert all(line.isascii() for line in text.splitlines())
    assert "False positives at effect 0 (" in text and "10 tasks x 1 repeat" not in text
    assert "# Power plan" in power.render_markdown(plan)


# --------------------------------------------------------------------------- pilot runs


def _pilot_run(tmp_path: Path, outcomes: dict[str, str]) -> RunStore:
    """A run dir whose baseline arm ("control") has ``outcomes[task]`` as pass/fail letters."""
    assert main(["init", str(tmp_path / "demo")]) == 0
    exp = load_experiment(tmp_path / "demo" / "experiment.toml")
    store = RunStore.create(tmp_path / "pilot", exp, planned_trials=0)
    for task, letters in outcomes.items():
        for rep, letter in enumerate(letters):
            status = {"p": "pass", "f": "fail", "e": "error"}[letter]
            for arm in ("control", "with-guide"):
                tid = f"{task}__{arm}__r{rep}"
                store.append(TrialRecord(tid, task, arm, rep, 0, status))
    return store


def test_pilot_model_uses_baseline_fractions(tmp_path, capsys):
    store = _pilot_run(tmp_path, {"fix-slugify": "ppp", "roman-numerals": "fpe"})
    capsys.readouterr()
    model = power.pilot_model(store.meta, store.records())
    assert model.name == "pilot"
    assert model.pilot_tasks == 2
    assert model.pilot_mean == pytest.approx(0.75)  # (3/3 + 1/2) / 2; the error is excluded
    assert any("only 2 pilot task(s)" in w for w in model.warnings)
    r = random.Random(0)
    draws = {model.sample(r) for _ in range(100)}
    assert len(draws) == 2 and all(0 < p < 1 for p in draws)  # shrunk away from 0 and 1


def test_pilot_model_without_baseline_trials_is_an_error(tmp_path, capsys):
    store = _pilot_run(tmp_path, {"fix-slugify": "ee"})
    capsys.readouterr()
    with pytest.raises(ValueError, match="no completed trials"):
        power.pilot_model(store.meta, store.records())


def test_cli_power_with_pilot_run(tmp_path, capsys):
    store = _pilot_run(tmp_path, {"fix-slugify": "pff", "roman-numerals": "fpp"})
    capsys.readouterr()
    code = main(
        [
            "power",
            str(store.run_dir),
            "--tasks",
            "10",
            "--repeats",
            "1",
            "--sims",
            "20",
            "--format",
            "json",
        ]
    )
    out, err = capsys.readouterr()
    assert code == 0
    data = json.loads(out)
    assert data["model"]["name"] == "pilot" and data["model"]["pilot_tasks"] == 2
    assert "warning: only 2 pilot task(s)" in err


# --------------------------------------------------------------------------- negative effects


def test_parse_options_accepts_negative_effects_and_explains_zero():
    o = power.parse_options(effect="-10,5,-2.5")
    assert o.effects == (-10.0, -2.5, 5.0)
    with pytest.raises(ValueError, match="non-zero"):
        power.parse_options(effect="0")
    with pytest.raises(ValueError, match="between -100 and 100"):
        power.parse_options(effect="-100")


def test_solve_shift_negative_mirrors_positive():
    probs = [0.2, 0.5, 0.7, 0.9]
    up, _ = power.solve_shift([1 - p for p in probs], 0.1)
    down, capped = power.solve_shift(probs, -0.1)
    assert not capped and down == pytest.approx(-up)
    arm = [power._expit(power.math.log(p / (1 - p)) + down) for p in probs]
    assert sum(arm) / 4 - sum(probs) / 4 == pytest.approx(-0.1, abs=1e-6)
    assert power.solve_shift([0.05, 0.1], -0.3)[1]  # cannot lose 30 points from 7.5%


def test_negative_effect_has_power_and_reports_realised_effect():
    model = power.beta_model()
    hurt = power.simulate_design(model, -20.0, 40, 3, alpha=0.05, sims=100, seed=0)
    help_ = power.simulate_design(model, 20.0, 40, 3, alpha=0.05, sims=100, seed=0)
    assert hurt.power > 0.8 and help_.power > 0.8
    assert hurt.realised == pytest.approx(-20.0, abs=1e-4)
    plan = power.run_plan(model, small_options(effect="-20,20"))
    text = power.render_text(plan)
    assert "-20  " in text and "+20  " in text
    assert "-20 pts:" in text


# --------------------------------------------------------------------------- headroom


@pytest.mark.parametrize("effect", ["10", "-10"])
def test_no_headroom_is_stated_explicitly(effect):
    always = 1.0 if float(effect) > 0 else 0.0
    model = power.DifficultyModel("beta", "saturated", lambda r: power._clip(always))
    plan = power.run_plan(model, small_options(effect=effect, tasks="10,20", repeats="1"))
    assert plan.no_headroom(float(effect))
    text = power.render_text(plan)
    assert "no headroom" in text and "try more tasks" not in text
    assert ("cannot gain" if float(effect) > 0 else "cannot lose") in text


def test_headroom_exists_for_a_mid_range_baseline():
    plan = power.run_plan(power.beta_model(), small_options(effect="5"))
    assert not plan.no_headroom(5.0)
    assert "no headroom" not in power.render_text(plan)


# --------------------------------------------------------------------------- false-positive check


def test_false_positive_check_runs_at_the_recommended_design():
    plan = power.run_plan(power.beta_model(), small_options(effect="20", tasks="10,40"))
    best = plan.recommendation(20.0)
    assert best is not None
    fp = plan.false_positive
    assert (fp.tasks, fp.repeats) == (best.tasks, best.repeats)
    assert fp.tasks > 10 or fp.repeats > 1
    text = power.render_text(plan)
    assert f"({fp.tasks} tasks x {fp.repeats} repeat" in text
    assert "recommended design" in text
    assert json.loads(power.render_json(plan))["false_positive_basis"] == plan.false_positive_basis


def test_false_positive_check_falls_back_to_the_largest_design():
    plan = power.run_plan(power.beta_model(), small_options(effect="1", tasks="10,20"))
    assert plan.recommendation(1.0) is None
    fp = plan.false_positive
    assert (fp.tasks, fp.repeats) == (20, 3)
    assert "largest design simulated" in power.render_text(plan)


def test_degenerate_false_positive_design_is_flagged():
    plan = power.run_plan(power.beta_model(), small_options(effect="1", tasks="4", repeats="1"))
    assert any("degenerate" in n for n in plan.notes())


# --------------------------------------------------------------------------- grid


def test_default_task_grid_is_fine_enough_to_find_25_tasks():
    tasks = power.parse_options().tasks
    assert 25 in tasks and 15 in tasks and tasks[0] == 10 and tasks[-1] == 200
