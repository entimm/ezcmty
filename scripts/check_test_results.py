"""Require nonempty JUnit reports containing only successful tests."""

from __future__ import annotations

import argparse
from pathlib import Path
from xml.etree import ElementTree


def check_report(path: Path) -> int:
    root = ElementTree.parse(path).getroot()
    cases = list(root.iter("testcase"))
    if not cases:
        raise ValueError(f"{path}: no tests were reported")
    incomplete = [
        f"{case.get('classname', '')}::{case.get('name', '')}"
        for case in cases
        if any(case.find(outcome) is not None for outcome in ("skipped", "failure", "error"))
    ]
    if incomplete:
        raise ValueError(f"{path}: tests did not pass: {', '.join(incomplete)}")
    for suite in root.iter("testsuite"):
        for outcome in ("skipped", "failures", "errors"):
            if int(suite.get(outcome, "0")):
                raise ValueError(f"{path}: suite reports {outcome}={suite.get(outcome)}")
    return len(cases)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reports", nargs="+", type=Path)
    options = parser.parse_args()
    try:
        total = sum(check_report(path) for path in options.reports)
    except (OSError, ElementTree.ParseError, ValueError) as error:
        parser.exit(1, f"{error}\n")
    print(f"Complete test verification passed: {total} tests")


if __name__ == "__main__":
    main()
