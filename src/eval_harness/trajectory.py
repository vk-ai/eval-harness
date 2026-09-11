"""Trajectory-aware eval: score the path, not only the final string.

Outcome-only judges miss unsafe or wasteful tool paths that still emit a
correct final answer. These types stay stdlib-only and framework-free.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Sequence

from .judges import Judge, exact
from .runner import TaskResult

PathJudge = Callable[["Trajectory"], bool]


@dataclass(frozen=True)
class Step:
    """One recorded action on an agent path."""

    action: str
    detail: str = ""


@dataclass(frozen=True)
class Trajectory:
    """Ordered steps plus the final answer string."""

    steps: tuple[Step, ...]
    final: str

    @property
    def actions(self) -> tuple[str, ...]:
        return tuple(s.action for s in self.steps)


def forbid_actions(*blocked: str) -> PathJudge:
    """Fail if any step action is in ``blocked`` (case-sensitive)."""

    banned = frozenset(blocked)

    def judge(traj: Trajectory) -> bool:
        return not any(step.action in banned for step in traj.steps)

    judge.__name__ = f"forbid_actions{blocked!r}"
    return judge


def require_actions(*required: str) -> PathJudge:
    """Fail unless every required action appears at least once (order-free)."""

    need = tuple(required)

    def judge(traj: Trajectory) -> bool:
        seen = set(traj.actions)
        return all(name in seen for name in need)

    judge.__name__ = f"require_actions{required!r}"
    return judge


def max_steps(limit: int) -> PathJudge:
    """Fail when the trajectory is longer than ``limit`` steps."""

    if limit < 0:
        raise ValueError("limit must be >= 0")

    def judge(traj: Trajectory) -> bool:
        return len(traj.steps) <= limit

    judge.__name__ = f"max_steps({limit})"
    return judge


def forbid_detail_substr(*needles: str, case_insensitive: bool = True) -> PathJudge:
    """Fail if any step detail contains a forbidden substring."""

    pats = tuple(needles)

    def judge(traj: Trajectory) -> bool:
        for step in traj.steps:
            hay = step.detail.lower() if case_insensitive else step.detail
            for needle in pats:
                n = needle.lower() if case_insensitive else needle
                if n and n in hay:
                    return False
        return True

    judge.__name__ = f"forbid_detail_substr{needles!r}"
    return judge


@dataclass(frozen=True)
class TrajectoryTask:
    """A task with an outcome judge plus zero or more path judges."""

    tid: str
    prompt: str
    expected: str
    judge: Judge = exact
    path_judges: tuple[PathJudge, ...] = ()


@dataclass
class TrajectoryResult:
    tid: str
    ok: bool
    outcome_ok: bool
    path_ok: bool
    actual: str
    expected: str
    steps: tuple[Step, ...]
    path_failures: tuple[str, ...] = ()


class TrajectoryHarness:
    """Run a callable that returns a :class:`Trajectory` per prompt."""

    def __init__(self, tasks: Sequence[TrajectoryTask]) -> None:
        if not tasks:
            raise ValueError("need at least one task")
        self.tasks = list(tasks)

    def run(self, fn: Callable[[str], Trajectory]) -> list[TrajectoryResult]:
        out: list[TrajectoryResult] = []
        for task in self.tasks:
            traj = fn(task.prompt)
            if not isinstance(traj, Trajectory):
                raise TypeError("agent must return a Trajectory")
            outcome_ok = task.judge(task.expected, traj.final)
            failures: list[str] = []
            for path_judge in task.path_judges:
                if not path_judge(traj):
                    failures.append(getattr(path_judge, "__name__", path_judge.__class__.__name__))
            path_ok = not failures
            out.append(
                TrajectoryResult(
                    tid=task.tid,
                    ok=outcome_ok and path_ok,
                    outcome_ok=outcome_ok,
                    path_ok=path_ok,
                    actual=traj.final,
                    expected=task.expected,
                    steps=traj.steps,
                    path_failures=tuple(failures),
                )
            )
        return out

    def score(self, results: Sequence[TrajectoryResult]) -> float:
        if not results:
            return 0.0
        return sum(1 for r in results if r.ok) / len(results)

    def report(self, results: Sequence[TrajectoryResult]) -> str:
        passed = sum(1 for r in results if r.ok)
        lines = ["# eval-harness (trajectory)", "", f"Passed {passed}/{len(results)}", ""]
        for r in results:
            mark = "PASS" if r.ok else "FAIL"
            lines.append(f"- `{r.tid}` **{mark}** (outcome={'ok' if r.outcome_ok else 'fail'}, path={'ok' if r.path_ok else 'fail'})")
            if not r.outcome_ok:
                lines.append(f"  - expected: {r.expected!r}")
                lines.append(f"  - actual: {r.actual!r}")
            if not r.path_ok:
                lines.append(f"  - path failures: {', '.join(r.path_failures)}")
                actions = ", ".join(s.action for s in r.steps) or "(none)"
                lines.append(f"  - actions: {actions}")
        return "\n".join(lines) + "\n"


def as_task_results(results: Sequence[TrajectoryResult]) -> list[TaskResult]:
    """Project trajectory results into plain TaskResult rows (``ok`` already combines path)."""
    return [
        TaskResult(tid=r.tid, ok=r.ok, actual=r.actual, expected=r.expected)
        for r in results
    ]
