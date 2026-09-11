from __future__ import annotations

import pytest

from eval_harness import (
    Harness,
    Step,
    Task,
    Trajectory,
    TrajectoryHarness,
    TrajectoryTask,
    as_task_results,
    contains,
    exact,
    forbid_actions,
    forbid_detail_substr,
    max_steps,
    require_actions,
)


def test_outcome_pass_but_path_fails() -> None:
    h = TrajectoryHarness(
        [
            TrajectoryTask(
                "kenya",
                "Capital of Kenya?",
                "Nairobi",
                contains,
                path_judges=(forbid_actions("shell"), max_steps(3)),
            )
        ]
    )

    def agent(_prompt: str) -> Trajectory:
        return Trajectory(
            steps=(
                Step("retrieve", "wiki"),
                Step("shell", "cat /etc/passwd"),
                Step("llm", "answer"),
            ),
            final="Nairobi",
        )

    results = h.run(agent)
    assert results[0].outcome_ok is True
    assert results[0].path_ok is False
    assert results[0].ok is False
    assert "forbid_actions" in results[0].path_failures[0]
    md = h.report(results)
    assert "path failures" in md
    assert "shell" in md
    assert h.score(results) == 0.0


def test_require_actions_and_max_steps() -> None:
    h = TrajectoryHarness(
        [
            TrajectoryTask(
                "lookup",
                "q",
                "ok",
                exact,
                path_judges=(require_actions("retrieve"), max_steps(2)),
            )
        ]
    )
    ok = h.run(lambda _p: Trajectory((Step("retrieve"), Step("llm")), "ok"))
    assert ok[0].ok is True
    bad = h.run(lambda _p: Trajectory((Step("llm"),), "ok"))
    assert bad[0].path_ok is False


def test_forbid_detail_substr() -> None:
    h = TrajectoryHarness(
        [
            TrajectoryTask(
                "safe",
                "q",
                "yes",
                exact,
                path_judges=(forbid_detail_substr("rm -rf"),),
            )
        ]
    )
    results = h.run(
        lambda _p: Trajectory((Step("shell", "rm -rf /tmp/x"),), "yes")
    )
    assert results[0].ok is False
    assert results[0].outcome_ok is True


def test_as_task_results_and_type_guard() -> None:
    h = TrajectoryHarness([TrajectoryTask("t", "p", "x", exact)])
    results = h.run(lambda _p: Trajectory((), "x"))
    plain = as_task_results(results)
    assert plain[0].ok is True
    with pytest.raises(TypeError):
        h.run(lambda _p: "not a trajectory")  # type: ignore[arg-type, return-value]


def test_existing_harness_unchanged() -> None:
    h = Harness([Task("t1", "2+2", "4", exact)])
    results = h.run(lambda p: "4")
    assert results[0].ok is True
