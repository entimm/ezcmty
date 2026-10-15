from pathlib import Path
from xml.etree import ElementTree

import pytest
from scripts.check_test_results import check_report


@pytest.mark.parametrize(
    "report",
    [
        '<testsuite tests="1"><testcase name="success"/></testsuite>',
        '<testsuites><testsuite><testcase name="success"/></testsuite></testsuites>',
    ],
    ids=["single-suite", "nested-suites"],
)
def test_successful_report_is_accepted(tmp_path: Path, report: str) -> None:
    path = tmp_path / "results.xml"
    path.write_text(report)
    assert check_report(path) == 1


@pytest.mark.parametrize(
    "report",
    [
        '<testsuite tests="0"/>',
        '<testsuite tests="1"/>',
        '<testsuite><testcase name="skipped"><skipped/></testcase></testsuite>',
        '<testsuite><testcase name="failed"><failure/></testcase></testsuite>',
        '<testsuite><testcase name="error"><error/></testcase></testsuite>',
        '<testsuite skipped="1"><testcase name="passed"/></testsuite>',
        '<testsuite errors="1"><testcase name="passed"/></testsuite>',
    ],
    ids=["empty", "missing-cases", "skipped", "failed", "error", "suite-skip", "suite-error"],
)
def test_incomplete_report_is_rejected(tmp_path: Path, report: str) -> None:
    path = tmp_path / "results.xml"
    path.write_text(report)
    with pytest.raises(ValueError):
        check_report(path)


def test_missing_report_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        check_report(tmp_path / "missing.xml")


def test_malformed_report_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "results.xml"
    path.write_text("<testsuite>")
    with pytest.raises(ElementTree.ParseError):
        check_report(path)
