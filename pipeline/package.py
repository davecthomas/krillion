"""Bundle built questions into a package: one committed file the game, or a
database import, can load.

    uv run python -m pipeline.package             # data/packages/default.jsonl.gz
    uv run python -m pipeline.package --name mine # data/packages/mine.jsonl.gz

A package is gzipped JSON Lines, one built question per line (the same
document pipeline.catalog writes), sorted by slug so a rebuild of unchanged
questions produces the same bytes. A manifest beside it records the count,
domains and build time, so a reviewer can see what changed without
unpacking it.

The format is meant to load straight into a database: one row per line, the
question's slug as the key and its answers as a JSON column (or one row per
answer).
"""

from __future__ import annotations

import argparse
import collections
import datetime as dt
import gzip
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "data"
QUESTIONS = ROOT / "catalog" / "questions"
PACKAGES = ROOT / "packages"
FORMAT = 1


def write(name: str = "default", questions: Path = QUESTIONS, packages: Path = PACKAGES) -> dict:
    docs = [json.loads(p.read_text()) for p in sorted(questions.glob("*.json"))]
    if not docs:
        raise SystemExit(f"no built questions in {questions}: run `make catalog` first")
    packages.mkdir(parents=True, exist_ok=True)
    path = packages / f"{name}.jsonl.gz"
    tmp = path.with_suffix(".tmp")
    # mtime=0 keeps the gzip header free of the build time, so same input means same bytes.
    with open(tmp, "wb") as raw, gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as gz:
        for d in sorted(docs, key=lambda d: d["slug"]):
            gz.write((json.dumps(d, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode())
    tmp.replace(path)
    manifest = {
        "format": FORMAT,
        "name": name,
        "questions": len(docs),
        "answers": sum(len(d["answers"]) for d in docs),
        "domains": dict(sorted(collections.Counter(d.get("domain", "") for d in docs).items())),
        "packaged_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "slugs": sorted(d["slug"] for d in docs),
    }
    (packages / f"{name}.manifest.json").write_text(json.dumps(manifest, indent=1, ensure_ascii=False) + "\n")
    return manifest


def read(path: Path):
    """Each question document in a package, in slug order."""
    with gzip.open(path, "rt", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                yield json.loads(line)


def unpack(packages: Path = PACKAGES, questions: Path = QUESTIONS) -> int:
    """Write every packaged question that has no local built file. Local files
    win, so a question you rebuilt is never overwritten by an older package."""
    questions.mkdir(parents=True, exist_ok=True)
    added = 0
    for path in sorted(packages.glob("*.jsonl.gz")):
        for doc in read(path):
            target = questions / f"{doc['slug']}.json"
            if target.exists():
                continue
            tmp = target.with_suffix(".tmp")
            tmp.write_text(json.dumps(doc, ensure_ascii=False))
            tmp.replace(target)
            added += 1
    return added


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--name", default="default", help="package name (default: default)")
    args = ap.parse_args()
    m = write(args.name)
    print(f"data/packages/{m['name']}.jsonl.gz: {m['questions']} questions, {m['answers']:,} answers")


if __name__ == "__main__":
    main()
