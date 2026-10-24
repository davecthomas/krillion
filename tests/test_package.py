import json

from krillion.bank import QuestionBank
from pipeline import package


def doc(slug, domain="d"):
    return {"slug": slug, "prompt": slug.replace("-", " ").capitalize(), "domain": domain,
            "answers": [{"id": "a", "name": "A", "aliases": [], "tier": 0}], "unverified": []}


def test_package_round_trips_and_is_reproducible(tmp_path):
    built, pkgs = tmp_path / "built", tmp_path / "packages"
    built.mkdir()
    for s in ("name-a-b", "name-a-a"):
        (built / f"{s}.json").write_text(json.dumps(doc(s)))
    m = package.write("default", built, pkgs)
    assert m["questions"] == 2 and m["slugs"] == ["name-a-a", "name-a-b"]
    first = (pkgs / "default.jsonl.gz").read_bytes()
    package.write("default", built, pkgs)
    assert (pkgs / "default.jsonl.gz").read_bytes() == first  # same input, same bytes
    assert [d["slug"] for d in package.read(pkgs / "default.jsonl.gz")] == ["name-a-a", "name-a-b"]


def test_bank_unpacks_packages_without_overwriting_local_builds(tmp_path):
    built, pkgs, fresh = tmp_path / "built", tmp_path / "packages", tmp_path / "fresh"
    built.mkdir()
    (built / "name-a-a.json").write_text(json.dumps(doc("name-a-a")))
    package.write("default", built, pkgs)
    fresh.mkdir()
    local = doc("name-a-a", domain="rebuilt here")
    (fresh / "name-a-a.json").write_text(json.dumps(local))
    (built / "name-a-z.json").write_text(json.dumps(doc("name-a-z")))
    package.write("default", built, pkgs)

    b = QuestionBank(questions=fresh, live=tmp_path / "live", packages=pkgs)
    assert b.remaining() == 2
    assert b.meta("name-a-a")["domain"] == "rebuilt here"
