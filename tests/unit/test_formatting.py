from app.presentation.formatting import format_size


def test_format_size_uses_decimal_units() -> None:
    assert format_size(999) == "999 B"
    assert format_size(1_000) == "1.0 KB"
    assert format_size(1_000_000) == "1.0 MB"
    assert format_size(1_000_000_000) == "1.00 GB"
