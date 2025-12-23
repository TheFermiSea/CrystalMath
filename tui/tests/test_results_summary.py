"""
Tests for the ResultsSummary widget.
"""

import pytest
from pathlib import Path
from src.tui.widgets import ResultsSummary


def test_results_summary_imports():
    """Test that ResultsSummary can be imported."""
    assert ResultsSummary is not None


def test_results_summary_instantiation():
    """Test that ResultsSummary can be instantiated."""
    widget = ResultsSummary()
    assert widget is not None


@pytest.mark.skip(reason="Requires Textual app context - widget.update() needs app.console")
def test_display_no_results():
    """Test displaying 'no results' message."""
    widget = ResultsSummary()
    widget.display_no_results()
    # Should not raise any exceptions


@pytest.mark.skip(reason="Requires Textual app context - widget.update() needs app.console")
def test_display_pending():
    """Test displaying pending job status."""
    widget = ResultsSummary()
    widget.display_pending("test_job")
    # Should not raise any exceptions


@pytest.mark.skip(reason="Requires Textual app context - widget.update() needs app.console")
def test_display_running():
    """Test displaying running job status."""
    widget = ResultsSummary()
    widget.display_running("test_job")
    # Should not raise any exceptions


@pytest.mark.skip(reason="Requires Textual app context - widget.update() needs app.console")
def test_display_error():
    """Test displaying error message."""
    widget = ResultsSummary()
    widget.display_error("Test error message")
    # Should not raise any exceptions


def test_fallback_parse_missing_file():
    """Test fallback parser with missing file."""
    widget = ResultsSummary()
    result = widget._fallback_parse(Path("/nonexistent/file.out"))
    assert isinstance(result, dict)


def test_fallback_parse_with_content(tmp_path):
    """Test fallback parser with actual content."""
    widget = ResultsSummary()

    # Create a fake output file
    output_file = tmp_path / "output.out"
    output_file.write_text("""
    CRYSTAL23 CALCULATION

    CYC   1  ETOT  -123.456789
    CYC   2  ETOT  -123.456799

    TOTAL ENERGY(DFT)(AU)( 2) -123.456799123456 DE-1.2E-09

    CONVERGENCE REACHED

    TTTTTTTT TOTAL CPU TIME:  123.45 SECONDS
    """)

    result = widget._fallback_parse(output_file)

    assert isinstance(result, dict)
    assert "final_energy" in result
    assert result["final_energy"] is not None
    assert "scf_cycles" in result
    assert result["scf_cycles"] == 2
    assert "is_converged" in result
    assert result["is_converged"] is True


def test_display_results_with_minimal_data(tmp_path):
    """Test displaying results with minimal data."""
    widget = ResultsSummary()
    work_dir = tmp_path / "job_001"
    work_dir.mkdir()

    # Create empty output file
    output_file = work_dir / "output.out"
    output_file.write_text("No meaningful content")

    # Should not raise exceptions
    widget.display_results(
        job_id=1,
        job_name="test_job",
        work_dir=work_dir,
        status="COMPLETED",
        final_energy=None,
        key_results=None,
        created_at=None,
        completed_at=None,
    )


def test_display_results_with_full_data(tmp_path):
    """Test displaying results with complete data."""
    widget = ResultsSummary()
    work_dir = tmp_path / "job_001"
    work_dir.mkdir()

    # Create output file with content
    output_file = work_dir / "output.out"
    output_file.write_text("""
    TOTAL ENERGY(DFT)(AU)( 10) -456.789012345678 DE-1.0E-10
    CONVERGENCE REACHED
    TTTTTTTT TOTAL CPU TIME:  234.56 SECONDS
    """)

    key_results = {
        "convergence": "CONVERGED",
        "errors": [],
        "warnings": ["Test warning"],
        "metadata": {"return_code": 0},
    }

    # Should not raise exceptions
    widget.display_results(
        job_id=1,
        job_name="test_job",
        work_dir=work_dir,
        status="COMPLETED",
        final_energy=-456.789012345678,
        key_results=key_results,
        created_at="2025-11-20 10:00:00",
        completed_at="2025-11-20 10:05:00",
    )


def test_display_results_with_errors(tmp_path):
    """Test displaying results for a failed job with errors."""
    widget = ResultsSummary()
    work_dir = tmp_path / "job_001"
    work_dir.mkdir()

    # Create output file with errors
    output_file = work_dir / "output.out"
    output_file.write_text("""
    ERROR: BASIS SET NOT FOUND
    FATAL ERROR IN CALCULATION
    ABNORMAL TERMINATION
    """)

    key_results = {
        "convergence": "FAILED",
        "errors": [
            "ERROR: BASIS SET NOT FOUND",
            "FATAL ERROR IN CALCULATION",
        ],
        "warnings": [],
        "metadata": {"return_code": 1},
    }

    # Should not raise exceptions
    widget.display_results(
        job_id=1,
        job_name="failed_job",
        work_dir=work_dir,
        status="FAILED",
        final_energy=None,
        key_results=key_results,
        created_at="2025-11-20 10:00:00",
        completed_at="2025-11-20 10:01:00",
    )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
