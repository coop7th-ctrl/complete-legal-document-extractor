"""Regression tests for benchmark scoring semantics."""

from benchmark.build_corpus import Injection, score


def test_unknown_reporter_rejection_is_not_counted_as_recall_failure():
    """An extraction-only benchmark must not require unknown reporters to match."""
    text = "Fictional v. Nonexistent, 1 Fake. 1 (2050)"
    probe = Injection(
        text=text,
        kind="case",
        offset=0,
        expect={},
        expected_extraction=False,
    )

    result = score(text, [probe])

    assert result["injected"] == 0
    assert result["found"] == 0
    assert result["rejected"] == 1
    assert result["unexpected_matches"] == []
    assert result["missed"] == []
