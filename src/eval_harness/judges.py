from __future__ import annotations

import re
from typing import Callable

Judge = Callable[[str, str], bool]


def exact(expected: str, actual: str) -> bool:
    return expected.strip() == actual.strip()


def contains(expected: str, actual: str) -> bool:
    return expected.lower() in actual.lower()


def regex(expected: str, actual: str) -> bool:
    return re.search(expected, actual, flags=re.IGNORECASE | re.DOTALL) is not None
