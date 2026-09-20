"""Build a benchmark corpus and measure extraction against known ground truth.

Source documents are read in place and never copied or modified. Only derived
plain text and results are written, into benchmark/corpus/, which is ignored by
git because these are real client filings.

Method
------
Hand-labelling a corpus is expensive, so recall is measured against *injected*
citations instead: known strings are spliced into real documents at known
offsets, and extraction is scored on whether it recovers them exactly.

This measures recall on the kinds of citation injected. It says nothing about
citations already present in the source text that the extractor misses -- those
are unknown unknowns and still need eyes on them. Precision is reported as a
raw count for manual review rather than as a score, for the same reason.

A note on "poisoning": impossible authority numbers that use a recognized
reporter or code are still extraction targets. Whether they exist is a question
for a downstream verifier. An invented reporter such as `Fake.`, however, is
not an extraction target for this reporters-db-backed stack; it is retained as
an explicit rejection probe and excluded from extraction-recall scoring.
"""

from __future__ import annotations

import json
import random
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pymupdf

from caselaw.group import group_citations

ROOT = Path(__file__).parent
CORPUS = ROOT / "corpus"

SECTION = "§"

# Citations spliced into documents. Each is well-formed; the point is whether
# extraction recovers the exact span and metadata.
CLEAN_INJECTIONS = [
    # (text, kind, what we expect to recover)
    (
        "Monell v. Department of Social Services, 436 U.S. 658, 690-91 (1978)",
        "case",
        {"plaintiff": "Monell", "year": 1978, "reporter": "U.S."},
    ),
    (
        "Bell Atlantic Corp. v. Twombly, 550 U.S. 544, 570 (2007)",
        "case",
        {"plaintiff": "Bell Atlantic Corp.", "year": 2007, "reporter": "U.S."},
    ),
    (
        "Schneider v. City of Grand Junction, 717 F.3d 760, 770 (10th Cir. 2013)",
        "case",
        {"plaintiff": "Schneider", "year": 2013, "reporter": "F.3d"},
    ),
    (
        "Graham v. Connor, 490 U.S. 386, 395 (1989)",
        "case",
        {"plaintiff": "Graham", "year": 1989, "reporter": "U.S."},
    ),
    (
        f"42 U.S.C. {SECTION} 1983",
        "statute",
        {"source": "U.S. Code"},
    ),
    (
        f"C.R.S. {SECTION} 24-72-303(1)",
        "statute",
        {"source": "Colorado Revised Statutes"},
    ),
    (
        f"N.R.S. {SECTION} 200.471",
        "statute",
        {"source": "Nevada Revised Statutes"},
    ),
    (
        "Fed. R. Civ. P. 12(b)(6)",
        "rule",
        {"source": "Federal Rules of Civil Procedure"},
    ),
    ("Fed. R. Evid. 702", "rule", {"source": "Federal Rules of Evidence"}),
    (
        f"28 C.F.R. {SECTION} 20.21",
        "regulation",
        {"source": "Code of Federal Regulations"},
    ),
]

# Awkward but real forms. These are the ones that break naive extractors.
HARD_INJECTIONS = [
    (
        "Bd. of Cnty. Comm’rs v. Brown, 520 U.S. 397, 404 (1997)",
        "case",
        {"plaintiff": "Bd. of Cnty. Comm’rs", "year": 1997},
    ),
    (
        "Waller v. City & County of Denver, 932 F.3d 1277, 1284 (10th Cir. 2019)",
        "case",
        {"plaintiff": "Waller", "defendant": "City & County of Denver"},
    ),
    (
        f"{SECTION} 24-72-305, C.R.S.",
        "statute",
        {"source": "Colorado Revised Statutes"},
    ),
]

# Fictitious or impossible probes. Recognized reporters and code names should
# still extract; the unknown reporter should be rejected.
MALFORMED_INJECTIONS = [
    ("Smith v. Jones, 999 F.4th 1234 (10th Cir. 2099)", "case", {}),
    ("Fictional v. Nonexistent, 1 Fake. 1 (2050)", "case", {}, False),
    (f"42 U.S.C. {SECTION} 99999999", "statute", {}),
    ("Fed. R. Evid. 9999", "rule", {}),
    (f"C.R.S. {SECTION} 00-00-000", "statute", {}),
]


@dataclass
class Injection:
    text: str
    kind: str
    offset: int
    expect: dict
    expected_extraction: bool = True


def page_text(path: Path) -> str:
    with pymupdf.open(path) as doc:
        return "".join(p.get_text("text", sort=True) for p in doc)


def sentence_boundaries(text: str) -> list[int]:
    """Offsets after a sentence-ending period followed by a capital."""
    return [m.start() for m in re.finditer(r"(?<=\.)\s+(?=[A-Z])", text)]


def inject(
    text: str, items: list[tuple], rng: random.Random
) -> tuple[str, list[Injection]]:
    """Splice citations in at sentence boundaries, recording true offsets."""
    spots = sentence_boundaries(text)
    if len(spots) < len(items) + 2:
        return text, []
    chosen = sorted(rng.sample(spots[1:-1], len(items)))

    out = []
    injections: list[Injection] = []
    cursor = 0
    shift = 0
    for spot, item in zip(chosen, items):
        body, kind = item[0], item[1]
        expect = item[2] if len(item) > 2 else {}
        sentence = f" See {body}. "
        out.append(text[cursor:spot])
        # Offset of the citation body within the final text.
        start = spot + shift + len(" See ")
        expected_extraction = item[3] if len(item) > 3 else True
        injections.append(Injection(body, kind, start, expect, expected_extraction))
        out.append(sentence)
        shift += len(sentence)
        cursor = spot
    out.append(text[cursor:])
    return "".join(out), injections


def score(text: str, injections: list[Injection]) -> dict:
    result = group_citations(text)

    case_spans = {
        (c.span[0], c.span[1]): c
        for g in result.groups
        for c in (g.header, *g.children)
    }
    case_spans.update({(c.span[0], c.span[1]): c for c in result.orphans})
    auth_spans = {
        (a.span[0], a.span[1]): a
        for grp in result.authorities
        for a in (grp.header, *grp.children)
    }

    found, rejected, missed, wrong, unexpected_matches = 0, 0, [], [], []
    for item in injections:
        window = (item.offset, item.offset + len(item.text))
        if item.kind == "case":
            hit = next(
                (
                    c
                    for (s, e), c in case_spans.items()
                    if s >= window[0] and e <= window[1] + 2
                ),
                None,
            )
            if not item.expected_extraction:
                if hit is None:
                    rejected += 1
                else:
                    unexpected_matches.append(item.text)
                continue
            if hit is None:
                missed.append(item.text)
                continue
            found += 1
            for key, value in item.expect.items():
                actual = getattr(hit, key, None)
                if key == "reporter":
                    ok = actual == value
                else:
                    ok = actual == value
                if not ok:
                    wrong.append(f"{item.text[:34]!r}: {key}={actual!r} want {value!r}")
        else:
            hit = next(
                (
                    a
                    for (s, e), a in auth_spans.items()
                    if s >= window[0] - 2 and e <= window[1] + 2
                ),
                None,
            )
            if not item.expected_extraction:
                if hit is None:
                    rejected += 1
                else:
                    unexpected_matches.append(item.text)
                continue
            if hit is None:
                missed.append(item.text)
                continue
            found += 1
            for key, value in item.expect.items():
                if getattr(hit, key, None) != value:
                    wrong.append(
                        f"{item.text[:34]!r}: {key}={getattr(hit, key, None)!r} want {value!r}"
                    )

    expected_count = sum(item.expected_extraction for item in injections)
    return {
        "injected": expected_count,
        "found": found,
        "recall": round(found / expected_count, 4) if expected_count else None,
        "rejected": rejected,
        "unexpected_matches": unexpected_matches,
        "missed": missed,
        "metadata_errors": wrong,
        "total_cases": len(result.groups),
        "total_authorities": len(result.authorities),
    }


def main(paths: list[Path], seed: int = 20260920) -> int:
    CORPUS.mkdir(exist_ok=True)
    rng = random.Random(seed)
    report = []

    for index, path in enumerate(paths):
        try:
            text = page_text(path)
        except Exception as exc:  # noqa: BLE001
            print(f"  !! {path.name}: {exc}", file=sys.stderr)
            continue

        poisoned = index < 5  # first five get injections
        if poisoned:
            items = CLEAN_INJECTIONS + HARD_INJECTIONS + MALFORMED_INJECTIONS
            text, injections = inject(text, items, rng)
        else:
            injections = []

        slug = re.sub(r"[^a-z0-9]+", "_", path.stem.lower())[:48]
        name = f"{index:02d}_{'poisoned' if poisoned else 'clean'}_{slug}"
        (CORPUS / f"{name}.txt").write_text(text, encoding="utf-8")

        row = {
            "index": index,
            "source": str(path),
            "name": name,
            "poisoned": poisoned,
            "chars": len(text),
        }
        if injections:
            (CORPUS / f"{name}.truth.json").write_text(
                json.dumps([asdict(i) for i in injections], indent=2),
                encoding="utf-8",
            )
            row.update(score(text, injections))
        else:
            result = group_citations(text)
            row.update(
                {
                    "total_cases": len(result.groups),
                    "total_authorities": len(result.authorities),
                }
            )
        report.append(row)

    (CORPUS / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(
        f"\n{'doc':<44} {'inj':>4} {'found':>6} {'recall':>7} {'cases':>6} {'auth':>5}"
    )
    print("-" * 80)
    for row in report:
        print(
            f"{row['name'][:44]:<44} "
            f"{row.get('injected', '-'):>4} {row.get('found', '-'):>6} "
            f"{row.get('recall', '-'):>7} "
            f"{row.get('total_cases', '-'):>6} {row.get('total_authorities', '-'):>5}"
        )

    scored = [r for r in report if r.get("injected")]
    if scored:
        total_inj = sum(r["injected"] for r in scored)
        total_found = sum(r["found"] for r in scored)
        print(
            f"\nOVERALL injected recall: {total_found}/{total_inj} = "
            f"{total_found / total_inj:.1%}"
        )
        errs = [e for r in scored for e in r["metadata_errors"]]
        miss = [m for r in scored for m in r["missed"]]
        rejected = sum(r["rejected"] for r in scored)
        unexpected = [m for r in scored for m in r["unexpected_matches"]]
        print(f"metadata errors: {len(errs)}")
        for e in errs[:15]:
            print("   ", e)
        print(f"missed: {len(miss)}")
        for m in miss[:15]:
            print("   ", m)
        print(
            f"unknown-format rejection probes: "
            f"{rejected}/{rejected + len(unexpected)} passed"
        )
        print(f"unexpected matches: {len(unexpected)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main([Path(p) for p in sys.argv[1:]]))
