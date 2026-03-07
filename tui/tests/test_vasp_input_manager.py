from src.tui.screens.vasp_input_manager import (
    parse_band_line_density,
    validate_vasp_job_name,
)


def test_parse_band_line_density_requires_positive_integer() -> None:
    """Band-path density parsing rejects zero, negatives, and preserves valid input."""
    assert parse_band_line_density("12") == 12

    for invalid in ("0", "-4", "abc"):
        try:
            parse_band_line_density(invalid)
        except ValueError:
            pass
        else:
            raise AssertionError(f"Expected ValueError for {invalid!r}")


def test_validate_vasp_job_name_blocks_path_characters() -> None:
    """VASP job names must stay safe for work-directory creation."""
    assert validate_vasp_job_name("si_band_job") is None
    assert validate_vasp_job_name("job-42") is None

    assert validate_vasp_job_name("../escape") is not None
    assert validate_vasp_job_name("nested/path") is not None
    assert validate_vasp_job_name("bad.name") is not None
