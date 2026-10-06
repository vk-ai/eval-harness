from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from eval_harness import (
    Harness,
    RunRecord,
    Step,
    Task,
    TaskResult,
    Trajectory,
    TrajectoryHarness,
    TrajectoryTask,
    compare,
    contains,
    exact,
    load_results,
    mcnemar_p,
    save_results,
)
from eval_harness.__main__ import main


def _results(**oks: bool) -> list[TaskResult]:
    return [TaskResult(tid=t, ok=ok, actual="", expected="") for t, ok in oks.items()]


@dataclass
class Graded:
    tid: str
    ok: bool
    score: float


def test_save_and_load_roundtrip_is_sorted_and_stable(tmp_path: Path) -> None:
    p = tmp_path / "nested" / "base.json"
    save_results(_results(b=False, a=True), p, meta={"commit": "abc"})
    data = json.loads(p.read_text())
    assert list(data["cases"]) == ["a", "b"]
    assert data["score"] == 0.5 and data["passed"] == 1 and data["total"] == 2
    rec = load_results(p)
    assert rec.cases["a"].ok and not rec.cases["b"].ok
    assert rec.meta == {"commit": "abc"}
    first = p.read_text()
    save_results(rec, p)
    assert p.read_text() == first


def test_known_failure_does_not_fail_but_new_failure_does() -> None:
    base = _results(easy=True, hard=False, mid=True)
    same = _results(easy=True, hard=False, mid=True)
    cmp = compare(base, same)
    assert cmp.ok and cmp.exit_code == 0
    assert [d.tid for d in cmp.unchanged] == ["easy", "hard", "mid"]

    worse = _results(easy=True, hard=False, mid=False)
    cmp = compare(base, worse)
    assert not cmp.ok and cmp.exit_code == 1
    assert [d.tid for d in cmp.regressions] == ["mid"]
    assert "REGRESSION" in cmp.report()
    assert "`mid`: PASS → FAIL" in cmp.report()


def test_case_regression_fails_even_when_aggregate_improves() -> None:
    base = _results(a=True, b=False, c=False)
    cur = _results(a=False, b=True, c=True)
    cmp = compare(base, cur, tolerance=1.0)
    assert cmp.score_delta > 0
    assert [d.tid for d in cmp.regressions] == ["a"]
    assert [d.tid for d in cmp.fixes] == ["b", "c"]
    assert not cmp.ok


def test_aggregate_tolerance_on_graded_scores() -> None:
    base = [Graded("a", True, 0.90), Graded("b", True, 0.80)]
    cur = [Graded("a", True, 0.88), Graded("b", True, 0.79)]
    # Small per-case dips within case tolerance; aggregate within tolerance.
    assert compare(base, cur, tolerance=0.02, case_tolerance=0.05).ok
    # Same dips with zero case tolerance are per-case regressions.
    assert not compare(base, cur, tolerance=0.02).ok
    # Aggregate drop beyond tolerance fails even when each case is within its tolerance.
    cmp = compare(base, cur, tolerance=0.01, case_tolerance=0.05)
    assert cmp.aggregate_regressed and not cmp.ok and not cmp.regressions
    assert "aggregate score dropped" in cmp.report()


def test_missing_and_new_tasks() -> None:
    base = _results(a=True, gone=True)
    cur = _results(a=True, added=False)
    cmp = compare(base, cur)
    assert [d.tid for d in cmp.missing] == ["gone"]
    assert [d.tid for d in cmp.new] == ["added"]
    assert not cmp.ok  # missing counts by default
    assert compare(base, cur, missing_is_regression=False).ok  # new failing task never fails


def test_mcnemar_p_values() -> None:
    assert mcnemar_p(0, 0) == 1.0
    assert mcnemar_p(5, 5) == 1.0
    assert mcnemar_p(0, 6) == pytest.approx(2 / 64)
    assert mcnemar_p(10, 0) < 0.01


def test_harness_save_and_compare(tmp_path: Path) -> None:
    h = Harness([Task("t1", "2+2", "4", exact), Task("t2", "hi", "hello", contains)])
    base = tmp_path / "baseline.json"
    h.save(h.run(lambda p: "4" if p == "2+2" else "hello there"), str(base), model="v1")
    assert load_results(base).meta == {"model": "v1"}
    cmp = h.compare(h.run(lambda p: "5" if p == "2+2" else "hello"), str(base))
    assert [d.tid for d in cmp.regressions] == ["t1"]


def test_trajectory_results_can_be_baselined(tmp_path: Path) -> None:
    th = TrajectoryHarness([TrajectoryTask("k", "Capital of Kenya?", "Nairobi", contains)])
    rows = th.run(lambda p: Trajectory(steps=(Step("llm"),), final="Nairobi"))
    p = tmp_path / "t.json"
    save_results(rows, p)
    assert compare(p, rows).ok


def test_duplicate_ids_and_bad_files_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        save_results(_results(a=True) + _results(a=False), tmp_path / "x.json")
    bad = tmp_path / "bad.json"
    bad.write_text('{"nope": 1}')
    with pytest.raises(ValueError):
        load_results(bad)
    with pytest.raises(ValueError):
        compare(_results(a=True), _results(a=True), tolerance=-1)


def test_cli_compare_exit_codes_and_report(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    base, cur, out = tmp_path / "b.json", tmp_path / "c.json", tmp_path / "r.md"
    save_results(_results(a=True, b=False), base)
    save_results(_results(a=True, b=True), cur)
    assert main(["compare", str(base), str(cur), "--report", str(out)]) == 0
    assert "OK — no regressions" in out.read_text()
    save_results(_results(a=False, b=True), cur)
    assert main(["compare", str(base), str(cur)]) == 1
    assert main(["compare", str(base), str(tmp_path / "missing.json")]) == 2
    capsys.readouterr()


def test_cli_save_baseline_refuses_regressed_overwrite(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    base, cur = tmp_path / "baseline.json", tmp_path / "current.json"
    save_results(_results(a=True, b=False), cur)
    assert main(["save-baseline", str(cur), str(base)]) == 0  # first save
    save_results(_results(a=True, b=True), cur)
    assert main(["save-baseline", str(cur), str(base)]) == 0  # improvement accepted
    assert load_results(base).passed == 2
    save_results(_results(a=False, b=True), cur)
    assert main(["save-baseline", str(cur), str(base)]) == 1  # regression refused
    assert load_results(base).passed == 2
    assert "refusing to overwrite" in capsys.readouterr().err
    assert main(["save-baseline", str(cur), str(base), "--force"]) == 0
    assert isinstance(load_results(base), RunRecord) and load_results(base).passed == 1
