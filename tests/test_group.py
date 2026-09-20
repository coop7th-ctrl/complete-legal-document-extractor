"""Tests for citation grouping and quote attribution."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from caselaw.group import group_citations

BRIEF = (
    'The Court held otherwise. "Congress did not intend municipalities to be '
    "held liable unless action pursuant to official municipal policy caused a "
    'constitutional tort." Monell v. Department of Social Services, 436 U.S. '
    "658, 691 (1978). The Tenth Circuit applied it in Schneider v. City of "
    "Grand Junction, 717 F.3d 760, 770 (10th Cir. 2013). Id. at 771. "
    "Schneider, 717 F.3d at 772."
)

JARDINES_MULTILINE = (
    "Florida v. Jardines, 569 U.S. 1 (2013). The implied license permits officers "
    "to \u201capproach the home and knock, precisely because that is no more than any "
    "private\n\ncitizen might do.\u201d Jardines, 569 U.S. at 8."
)


def test_full_citations_become_group_headers():
    result = group_citations(BRIEF)
    assert [g.case_name for g in result.groups] == [
        "Monell v. Department of Social Services",
        "Schneider v. City of Grand Junction",
    ]


def test_id_and_short_forms_cascade_under_their_full_citation():
    result = group_citations(BRIEF)
    schneider = result.groups[1]
    kinds = [c.kind for c in schneider.children]
    assert "IdCitation" in kinds
    assert "ShortCaseCitation" in kinds


def test_a_quotation_is_attributed_to_the_citation_that_follows_it():
    result = group_citations(BRIEF)
    monell = result.groups[0]
    assert len(monell.quotes) == 1
    assert monell.quotes[0].text.startswith("Congress did not intend")
    assert monell.quotes[0].pin_cite == "691"


def test_pdf_line_wrapping_does_not_discard_a_multiline_quotation():
    result = group_citations(JARDINES_MULTILINE)
    jardines = next(g for g in result.groups if g.case_name == "Florida v. Jardines")

    assert [quote.text for quote in jardines.quotes] == [
        (
            "approach the home and knock, precisely because that is no more than "
            "any private citizen might do."
        )
    ]
    assert jardines.quotes[0].pin_cite == "8"


def test_unattributed_quotation_is_retained_instead_of_discarded():
    text = "The private door displayed the warning “No Trespassing.”"

    result = group_citations(text).as_dict()

    assert [quote["text"] for quote in result["unattributedQuotes"]] == [
        "No Trespassing."
    ]
    assert result["unattributedQuotes"][0]["attribution_status"] == "unattributed"
    assert result["stats"]["quotes"] == 1
    assert result["stats"]["linkedQuotes"] == 0
    assert result["stats"]["unattributedQuotes"] == 1


def test_quotation_followed_by_id_is_linked_without_treating_every_id_as_a_quote():
    text = (
        "Monell v. Department of Social Services, 436 U.S. 658, 690 (1978). "
        "The Court called the rule \u201ca deliberate choice to follow a course of "
        "action.\u201d Id. at 690. Id. at 691 explains a different proposition."
    )

    result = group_citations(text)
    monell = next(
        g
        for g in result.groups
        if g.case_name == "Monell v. Department of Social Services"
    )

    assert len(monell.quotes) == 1
    assert monell.quotes[0].attribution_basis == "following_id"
    assert monell.quotes[0].pin_cite == "690"


def test_long_block_quotation_is_not_cut_off_at_four_hundred_characters():
    quoted = "constitutional text " * 30
    text = (
        "Monell v. Department of Social Services, 436 U.S. 658 (1978). Later, "
        f"\u201c{quoted}\u201d Monell, 436 U.S. at 690."
    )

    result = group_citations(text)
    monell = next(
        g
        for g in result.groups
        if g.case_name == "Monell v. Department of Social Services"
    )

    assert [quote.text for quote in monell.quotes] == [quoted.strip()]


def test_quotation_can_be_attributed_to_a_statute_instead_of_a_case():
    text = "The statute reaches every person acting “under color of law.” 42 U.S.C. § 1983."

    result = group_citations(text)
    section_1983 = next(
        group for group in result.authorities if "1983" in group.header.text
    )

    assert [quote.text for quote in section_1983.quotes] == ["under color of law."]
    assert section_1983.quotes[0].attribution_basis == "following_authority"


def test_quote_spans_round_trip_into_the_source():
    result = group_citations(BRIEF)
    for g in result.groups:
        for q in g.quotes:
            start, end = q.span
            assert q.text in BRIEF[start:end]
            assert q.raw_text == BRIEF[start:end]


def test_groups_are_in_document_order():
    result = group_citations(BRIEF)
    starts = [g.header.span[0] for g in result.groups]
    assert starts == sorted(starts)


def test_every_citation_appears_exactly_once():
    result = group_citations(BRIEF)
    seen = [c.span for g in result.groups for c in (g.header, *g.children)] + [
        c.span for c in result.orphans
    ]
    assert len(seen) == len(set(seen))


def test_stats_are_consistent():
    result = group_citations(BRIEF).as_dict()
    counted = sum(1 + len(g["children"]) for g in result["groups"])
    assert result["stats"]["citations"] == counted + len(result["orphans"])


def test_empty_text_yields_nothing():
    result = group_citations("")
    assert result.groups == [] and result.orphans == []
