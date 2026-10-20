"""Incomplete execution cannot become a passing verification report."""
import pytest

from monsoon.verify import test_summary as summarise_report


@pytest.mark.parametrize("counts, expected", [
    ('tests="3" failures="0" errors="0" skipped="0"', "passed"),
    ('tests="3" failures="0" errors="0" skipped="1"', "failed"),
    ('tests="3" failures="1" errors="0" skipped="0"', "failed"),
    ('tests="3" failures="0" errors="1" skipped="0"', "failed"),
    ('tests="0" failures="0" errors="0" skipped="0"', "failed"),
])
def test_incomplete_or_failed_execution_is_not_passed(tmp_path, counts, expected):
    path = tmp_path / "pytest.xml"
    path.write_text(f"<testsuites><testsuite {counts}/></testsuites>", encoding="utf-8")
    assert summarise_report(path)["status"] == expected


def test_missing_report_is_not_run(tmp_path):
    assert summarise_report(tmp_path / "missing.xml")["status"] == "not_run"
