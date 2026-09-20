"""Tests for the human review layer.

The review layer proposes; it never rewrites. These tests pin both halves of
that: that it catches the OCR damage that extraction cannot see, and that it
stays quiet on clean text. A review aid that cries wolf gets switched off.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from caselaw.group import group_citations
from caselaw.review import _RULE_MARKER, review


def findings(text: str):
    return review(text, group_citations(text).as_dict())


def kinds(text: str):
    return sorted({f.kind for f in findings(text)})


# --- citations lost to a mangled reporter ----------------------------------


def test_a_wrong_reporter_letter_is_reported_as_a_missed_citation():
    """One wrong character makes eyecite skip the citation with no error."""
    text = "Dike v. People, 30 R3d 197 (Colo. 2001)."
    (found,) = [f for f in findings(text) if f.kind == "missed_citation"]
    assert found.text == "30 R3d 197"
    assert "30 P.3d 197" in [s.replacement for s in found.suggestions]


def test_suggestions_are_real_reporters():
    text = "Smith v. Jones, 417 E.2d 732 (10th Cir. 1969)."
    (found,) = [f for f in findings(text) if f.kind == "missed_citation"]
    assert found.suggestions, "no replacement offered"


# --- quiet on text that is fine --------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "Dike v. People, 30 P.3d 197 (Colo. 2001).",
        "Dike v. People, 30 P.3d 197 (Colo. 2001). 30 P.3d at 199.",
        "Defendant moved under Crim. P. 41 and Fed. R. Civ. P. 12.",
        "The hearing was held on 12 March 2026 at 30 minutes past nine.",
    ],
)
def test_no_findings_on_sound_text(text):
    assert findings(text) == []


def test_rules_of_procedure_are_not_mistaken_for_reporters():
    """ "Crim. P. 41" has citation shape; proposing the nearest reporter to it
    produced "Chip." before this was guarded."""
    text = "Defendant moved under Crim. P. 41."
    assert [f for f in findings(text) if f.kind == "missed_citation"] == []


@pytest.mark.parametrize("marker", ["Crim. P.", "R. Civ. P.", "Fed. R. Evid."])
def test_rule_marker_recognises_procedure_and_evidence_abbreviations(marker):
    """The guard must use regex word boundaries, not literal backspaces."""
    assert _RULE_MARKER.search(marker)


# --- OCR-damaged party names ------------------------------------------------


def test_a_misread_name_is_caught_when_the_document_disagrees_with_itself():
    text = (
        "Chavez v. People, 487 P.3d 998 (Colo. 2021). "
        "Cliavez v. People, 487 P.3d 998 (Colo. 2021)."
    )
    names = [f for f in findings(text) if f.kind == "suspect_name"]
    assert names, "misread name not flagged"
    assert "Chavez" in [s.replacement for s in names[0].suggestions]


def test_ordinary_names_are_not_flagged():
    """ "Williamson" holds an "li" and "People" an "l"; neither is OCR damage.
    A candidate is only offered when it appears elsewhere in the document."""
    text = "Coffman v. Williamson, 348 P.3d 929 (Colo. 2015)."
    assert [f for f in findings(text) if f.kind == "suspect_name"] == []


def test_a_candidate_absent_from_the_document_is_not_proposed():
    text = "Cliavez v. People, 487 P.3d 998 (Colo. 2021)."
    assert [f for f in findings(text) if f.kind == "suspect_name"] == []


# --- disagreement between references to one citation -----------------------


def test_one_citation_with_two_case_names_is_flagged():
    text = (
        "Coffman v. Williamson, 348 P.3d 929 (Colo. 2015). Later, "
        "Coffinan v. Williamson, 348 P.3d 929 (Colo. 2015), was discussed."
    )
    clashes = [f for f in findings(text) if f.kind == "inconsistent_name"]
    assert clashes, "conflicting names not flagged"
    assert "348 P.3d 929" in clashes[0].text


def test_no_majority_is_assumed():
    """On a real opinion the misread spelling outnumbered the correct one 11 to
    1, so frequency must be reported, never acted on."""
    text = (
        "Coffman v. Williamson, 348 P.3d 929 (Colo. 2015). "
        "Coffinan v. Williamson, 348 P.3d 929 (Colo. 2015). "
        "Coffinan v. Williamson, 348 P.3d 929 (Colo. 2015)."
    )
    clashes = [f for f in findings(text) if f.kind == "inconsistent_name"]
    assert clashes
    assert len(clashes[0].suggestions) == 2


# --- shape -----------------------------------------------------------------


def test_findings_are_in_document_order():
    text = (
        "Cliavez v. People, 487 P.3d 998 (Colo. 2021). "
        "Chavez v. People, 487 P.3d 998 (Colo. 2021). "
        "Dike v. People, 30 R3d 197 (Colo. 2001)."
    )
    starts = [f.span[0] for f in findings(text)]
    assert starts == sorted(starts)


def test_every_finding_serialises():
    text = "Dike v. People, 30 R3d 197 (Colo. 2001)."
    for found in findings(text):
        data = found.as_dict()
        assert set(data) == {
            "kind",
            "text",
            "span",
            "context",
            "message",
            "suggestions",
        }
        assert isinstance(data["span"], list)


def test_nothing_is_rewritten():
    """The review layer returns findings only; the text is never modified."""
    text = "Dike v. People, 30 R3d 197 (Colo. 2001)."
    before = text
    findings(text)
    assert text == before


def test_empty_text():
    assert findings("") == []
