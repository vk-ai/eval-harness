"""Baseline compare: fail CI only when results get worse than a saved run.

An absolute bar ("score >= 0.8") fails forever on a known-hard task and
misses a real drop that stays above the bar. Saving a baseline from `main`
and comparing each PR against it fails only on regressions:

- per case: a task whose score drops by more than ``case_tolerance``
  (for pass/fail tasks, PASS → FAIL), or a baseline task that disappeared;
- aggregate: the mean score drops by more than ``tolerance``.

Fixes, new tasks and still-failing tasks are reported but never fail.
Stdlib only; the file format is plain JSON so it diffs well in review.
"""

from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence, Union

FORMAT_VERSION = 1

PathLike = Union[str, "os.PathLike[str]"]


@dataclass(frozen=True)
class CaseRecord:
    """One task in a saved run. ``score`` is 1.0/0.0 for pass/fail judges."""

    tid: str
    ok: bool
    score: float


@dataclass(frozen=True)
class RunRecord:
    """A saved run: per-task records plus optional free-form metadata."""

    cases: Mapping[str, CaseRecord]
    meta: Mapping[str, Any] = field(default_factory=dict)

    @property
    def score(self) -> float:
        if not self.cases:
            return 0.0
        return sum(c.score for c in self.cases.values()) / len(self.cases)

    @property
    def passed(self) -> int:
        return sum(1 for c in self.cases.values() if c.ok)

    def to_json(self) -> dict[str, Any]:
        return {
            "version": FORMAT_VERSION,
            "score": round(self.score, 6),
            "passed": self.passed,
            "total": len(self.cases),
            "meta": dict(self.meta),
            "cases": {
                tid: {"ok": c.ok, "score": c.score}
                for tid, c in sorted(self.cases.items())
            },
        }


def _case_from_result(r: Any) -> CaseRecord:
    tid = str(getattr(r, "tid"))
    ok = bool(getattr(r, "ok"))
    raw = getattr(r, "score", None)
    score = float(ok) if raw is None else float(raw)
    if not math.isfinite(score):
        raise ValueError(f"task {tid!r}: score must be finite")
    return CaseRecord(tid=tid, ok=ok, score=score)


def to_record(results: Iterable[Any], meta: Mapping[str, Any] | None = None) -> RunRecord:
    """Build a :class:`RunRecord` from ``TaskResult``/``TrajectoryResult`` rows.

    Any object with ``tid`` and ``ok`` works; an optional numeric ``score``
    attribute is used for graded judges.
    """
    cases: dict[str, CaseRecord] = {}
    for r in results:
        c = _case_from_result(r)
        if c.tid in cases:
            raise ValueError(f"duplicate task id: {c.tid!r}")
        cases[c.tid] = c
    return RunRecord(cases=cases, meta=dict(meta or {}))


def save_results(
    results: Iterable[Any] | RunRecord,
    path: PathLike,
    *,
    meta: Mapping[str, Any] | None = None,
) -> RunRecord:
    """Write results (or a RunRecord) to ``path`` as stable, sorted JSON."""
    record = results if isinstance(results, RunRecord) else to_record(results, meta)
    p = Path(path)
    if p.parent and not p.parent.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(record.to_json(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, p)
    return record


def load_results(path: PathLike) -> RunRecord:
    """Read a file written by :func:`save_results`."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict) or "cases" not in data:
        raise ValueError(f"{path}: not an eval-harness results file")
    version = data.get("version", FORMAT_VERSION)
    if version != FORMAT_VERSION:
        raise ValueError(f"{path}: unsupported results version {version!r}")
    cases: dict[str, CaseRecord] = {}
    for tid, c in dict(data["cases"]).items():
        ok = bool(c["ok"])
        cases[str(tid)] = CaseRecord(tid=str(tid), ok=ok, score=float(c.get("score", float(ok))))
    return RunRecord(cases=cases, meta=dict(data.get("meta") or {}))


def mcnemar_p(fixes: int, regressions: int) -> float:
    """Exact two-sided McNemar p-value on discordant pairs (informational)."""
    n = fixes + regressions
    if n == 0:
        return 1.0
    k = min(fixes, regressions)
    tail = sum(math.comb(n, i) for i in range(k + 1)) / (2**n)
    return min(1.0, 2 * tail)


@dataclass(frozen=True)
class CaseDelta:
    tid: str
    baseline: CaseRecord | None
    current: CaseRecord | None

    @property
    def delta(self) -> float:
        b = self.baseline.score if self.baseline else 0.0
        c = self.current.score if self.current else 0.0
        return c - b


@dataclass(frozen=True)
class Comparison:
    """Result of :func:`compare`. ``ok`` is False only on regressions."""

    baseline_score: float
    current_score: float
    tolerance: float
    case_tolerance: float
    regressions: tuple[CaseDelta, ...]
    fixes: tuple[CaseDelta, ...]
    unchanged: tuple[CaseDelta, ...]
    new: tuple[CaseDelta, ...]
    missing: tuple[CaseDelta, ...]
    missing_is_regression: bool = True

    @property
    def score_delta(self) -> float:
        return self.current_score - self.baseline_score

    @property
    def aggregate_regressed(self) -> bool:
        return self.score_delta < -self.tolerance - 1e-12

    @property
    def case_regressions(self) -> tuple[CaseDelta, ...]:
        extra = self.missing if self.missing_is_regression else ()
        return self.regressions + extra

    @property
    def ok(self) -> bool:
        return not self.case_regressions and not self.aggregate_regressed

    @property
    def exit_code(self) -> int:
        return 0 if self.ok else 1

    @property
    def p_value(self) -> float:
        return mcnemar_p(len(self.fixes), len(self.regressions))

    def report(self) -> str:
        verdict = "OK — no regressions" if self.ok else "REGRESSION"
        lines = [
            "# eval-harness baseline compare",
            "",
            f"**{verdict}**",
            "",
            "| | baseline | current | delta |",
            "|---|---|---|---|",
            f"| score | {self.baseline_score:.3f} | {self.current_score:.3f} | {self.score_delta:+.3f} |",
            "",
            f"Tolerance: aggregate {self.tolerance:g}, per case {self.case_tolerance:g}. "
            f"Regressions {len(self.regressions)}, fixes {len(self.fixes)}, "
            f"unchanged {len(self.unchanged)}, new {len(self.new)}, missing {len(self.missing)}. "
            f"McNemar p={self.p_value:.3g} (informational).",
            "",
        ]
        if self.aggregate_regressed:
            lines.append(
                f"- aggregate score dropped by {-self.score_delta:.3f} (> tolerance {self.tolerance:g})"
            )
            lines.append("")
        sections = [
            ("Regressions", self.regressions),
            ("Missing from current run" + (" (counted as regressions)" if self.missing_is_regression else ""), self.missing),
            ("Fixes", self.fixes),
            ("New tasks", self.new),
        ]
        for title, rows in sections:
            if not rows:
                continue
            lines.append(f"## {title}")
            lines.append("")
            for d in rows:
                b = _fmt(d.baseline)
                c = _fmt(d.current)
                lines.append(f"- `{d.tid}`: {b} → {c}")
            lines.append("")
        return "\n".join(lines).rstrip() + "\n"


def _fmt(c: CaseRecord | None) -> str:
    if c is None:
        return "—"
    mark = "PASS" if c.ok else "FAIL"
    return mark if c.score == float(c.ok) else f"{mark} ({c.score:.3f})"


def _as_record(x: RunRecord | Sequence[Any] | PathLike) -> RunRecord:
    if isinstance(x, RunRecord):
        return x
    if isinstance(x, (str, os.PathLike)):
        return load_results(x)
    return to_record(x)


def compare(
    baseline: RunRecord | Sequence[Any] | PathLike,
    current: RunRecord | Sequence[Any] | PathLike,
    *,
    tolerance: float = 0.0,
    case_tolerance: float = 0.0,
    missing_is_regression: bool = True,
) -> Comparison:
    """Compare ``current`` against ``baseline`` (records, result lists or paths).

    A case regresses when its score drops by more than ``case_tolerance``
    or its pass/fail flips from PASS to FAIL. The aggregate regresses when
    the mean score drops by more than ``tolerance``. Tasks only in the
    baseline are "missing" and count as regressions unless
    ``missing_is_regression=False`` (so deleting a task can't hide a drop).
    """
    if tolerance < 0 or case_tolerance < 0:
        raise ValueError("tolerances must be >= 0")
    b = _as_record(baseline)
    c = _as_record(current)
    regressions: list[CaseDelta] = []
    fixes: list[CaseDelta] = []
    unchanged: list[CaseDelta] = []
    new: list[CaseDelta] = []
    missing: list[CaseDelta] = []
    for tid in sorted(set(b.cases) | set(c.cases)):
        bc = b.cases.get(tid)
        cc = c.cases.get(tid)
        d = CaseDelta(tid=tid, baseline=bc, current=cc)
        if bc is None:
            new.append(d)
        elif cc is None:
            missing.append(d)
        elif (bc.ok and not cc.ok) or d.delta < -case_tolerance - 1e-12:
            regressions.append(d)
        elif (cc.ok and not bc.ok) or d.delta > case_tolerance + 1e-12:
            fixes.append(d)
        else:
            unchanged.append(d)
    # Aggregate over the shared tasks so adding/removing tasks doesn't move the bar.
    shared = sorted(set(b.cases) & set(c.cases))
    if shared:
        b_score = sum(b.cases[t].score for t in shared) / len(shared)
        c_score = sum(c.cases[t].score for t in shared) / len(shared)
    else:
        b_score, c_score = b.score, c.score
    return Comparison(
        baseline_score=b_score,
        current_score=c_score,
        tolerance=tolerance,
        case_tolerance=case_tolerance,
        regressions=tuple(regressions),
        fixes=tuple(fixes),
        unchanged=tuple(unchanged),
        new=tuple(new),
        missing=tuple(missing),
        missing_is_regression=missing_is_regression,
    )
