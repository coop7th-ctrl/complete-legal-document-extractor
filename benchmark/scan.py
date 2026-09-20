"""Scan a case archive for citation-rich filings worth benchmarking.

Reads only; never copies or modifies the source documents.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pymupdf

from caselaw.authorities import extract_authorities
from caselaw.extract import extract

# Filings that argue law; exhibits and transcripts rarely cite anything.
PROMISING = re.compile(
    r"brief|motion|response|reply|memo|opinion|order|complaint|answer|"
    r"argument|petition|appeal|ruling|decision",
    re.IGNORECASE,
)
SKIP = re.compile(
    r"exhibit|transcript|bates|invoice|receipt|blank|photo", re.IGNORECASE
)

MAX_BYTES = 12 * 1024 * 1024


def page_text(path: Path) -> str:
    with pymupdf.open(path) as doc:
        return "".join(p.get_text("text", sort=True) for p in doc)


def main(root: Path, out: Path) -> int:
    rows = []
    candidates = [
        p
        for p in root.rglob("*.pdf")
        if PROMISING.search(p.name)
        and not SKIP.search(p.name)
        and p.stat().st_size <= MAX_BYTES
    ]
    print(f"{len(candidates)} candidate filings", file=sys.stderr)

    for index, path in enumerate(candidates, 1):
        try:
            text = page_text(path)
        except Exception as exc:  # noqa: BLE001 - a corrupt file is data, not a crash
            print(f"  skip {path.name}: {exc}", file=sys.stderr)
            continue
        if len(text) < 500:
            continue
        cases = extract(text)
        auth = extract_authorities(text)
        full = [c for c in cases if c.kind == "FullCaseCitation"]
        rows.append(
            {
                "path": str(path),
                "case": path.relative_to(root).parts[1]
                if len(path.relative_to(root).parts) > 1
                else "?",
                "name": path.name,
                "chars": len(text),
                "full_cites": len(full),
                "all_cites": len(cases),
                "authorities": len(auth),
                "score": len(full) * 2 + len(auth),
            }
        )
        if index % 25 == 0:
            print(f"  {index}/{len(candidates)}", file=sys.stderr)

    rows.sort(key=lambda r: -r["score"])
    out.write_text(json.dumps(rows, indent=2), encoding="utf-8")
    print(f"\nwrote {len(rows)} rows to {out}", file=sys.stderr)

    print(f"\n{'score':>5} {'cases':>5} {'auth':>5} {'chars':>7}  matter / file")
    for row in rows[:25]:
        print(
            f"{row['score']:>5} {row['full_cites']:>5} {row['authorities']:>5} "
            f"{row['chars']:>7}  {row['case'][:22]:22} {row['name'][:52]}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(
        main(
            Path(sys.argv[1]),
            Path(sys.argv[2])
            if len(sys.argv) > 2
            else Path(__file__).parent / "scan.json",
        )
    )
