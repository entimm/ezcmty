import pytest

from backend_app.integrations.import_files.storage import safe_csv_cell, safe_download_name


@pytest.mark.parametrize(
    "value", ["=SUM(A1)", "+42", "-42", "@command", "  =cmd", "\t=cmd", "\r=cmd"]
)
def test_export_neutralizes_formula_cells(value: str) -> None:
    assert safe_csv_cell(value).startswith("'")


def test_export_preserves_ordinary_values_and_sanitizes_download_name() -> None:
    assert safe_csv_cell("普通文字") == "普通文字"
    assert safe_csv_cell(None) == ""
    assert safe_download_name('../a\r\n";b.csv') == "_a____b.csv"
