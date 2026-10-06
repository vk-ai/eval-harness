"""CLI: ``python -m eval_harness compare|save-baseline``.

    python -m eval_harness compare baseline.json current.json [--tolerance 0.02]
    python -m eval_harness save-baseline current.json baseline.json [--force]

``compare`` exits 0 when there are no regressions, 1 on regressions and 2
on usage/file errors. ``save-baseline`` copies a results file into place and
refuses to overwrite an existing baseline with a regressed run unless
``--force`` is passed.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence

from .baseline import compare, load_results, save_results


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m eval_harness", description=__doc__.split("\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("compare", help="compare a results file against a baseline")
    c.add_argument("baseline")
    c.add_argument("current")
    c.add_argument("--tolerance", type=float, default=0.0, help="allowed drop in mean score (default 0)")
    c.add_argument("--case-tolerance", type=float, default=0.0, help="allowed drop per case score (default 0)")
    c.add_argument("--allow-missing", action="store_true", help="tasks missing from current do not fail")
    c.add_argument("--report", help="also write the markdown report to this path")

    s = sub.add_parser("save-baseline", help="save/update the baseline from a results file")
    s.add_argument("current")
    s.add_argument("baseline")
    s.add_argument("--force", action="store_true", help="overwrite even if current regresses vs the old baseline")
    s.add_argument("--tolerance", type=float, default=0.0)
    s.add_argument("--case-tolerance", type=float, default=0.0)
    return p


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.cmd == "compare":
            cmp = compare(
                args.baseline,
                args.current,
                tolerance=args.tolerance,
                case_tolerance=args.case_tolerance,
                missing_is_regression=not args.allow_missing,
            )
            md = cmp.report()
            print(md, end="")
            if args.report:
                Path(args.report).write_text(md, encoding="utf-8")
            return cmp.exit_code
        current = load_results(args.current)
        if Path(args.baseline).exists() and not args.force:
            cmp = compare(
                args.baseline,
                current,
                tolerance=args.tolerance,
                case_tolerance=args.case_tolerance,
            )
            if not cmp.ok:
                print(cmp.report(), end="")
                print(
                    f"refusing to overwrite {args.baseline}: current run regresses "
                    "(pass --force to accept it as the new baseline)",
                    file=sys.stderr,
                )
                return 1
        rec = save_results(current, args.baseline)
        print(f"saved baseline {args.baseline}: {rec.passed}/{len(rec.cases)} passed, score {rec.score:.3f}")
        return 0
    except (OSError, ValueError, KeyError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
