"""Wikidata's SPARQL endpoint: discover categories and list their members.

Every query goes through http.get_json, so results cache to disk and 429s
back off. The endpoint allows about 60 seconds per query; the queries here
stay well under that for classes of playable size.
"""

from __future__ import annotations

from .http import get_json

SPARQL = "https://query.wikidata.org/sparql"
ENWIKI = "<https://en.wikipedia.org/>"
# A Wikipedia category that is not a list of members ("Category:Geography of Pakistan")
# has no class behind it. Requiring a parent class drops most of those.
DISCOVER = """
SELECT ?class ?classLabel ?catTitle WHERE {
  ?class wdt:P910 ?cat; wdt:P279 ?parent.
  ?catPage schema:about ?cat; schema:isPartOf %s; schema:name ?catTitle.
  ?class rdfs:label ?classLabel FILTER(lang(?classLabel) = "en")
} LIMIT %d OFFSET %d
"""
MEMBERS = """
SELECT DISTINCT ?title ?sitelinks WHERE {
  ?item wdt:P31/wdt:P279* wd:%s; wikibase:sitelinks ?sitelinks.
  ?page schema:about ?item; schema:isPartOf %s; schema:name ?title.
} LIMIT %d
"""
SITELINKS = """
SELECT ?title ?sitelinks WHERE {
  VALUES ?title { %s }
  ?page schema:about ?item; schema:isPartOf %s; schema:name ?title.
  ?item wikibase:sitelinks ?sitelinks.
}
"""


def query(sparql: str) -> list[dict]:
    data = get_json(SPARQL, {"query": " ".join(sparql.split()), "format": "json"})
    return [{k: v["value"] for k, v in row.items()} for row in data.get("results", {}).get("bindings", [])]


def qid(uri: str) -> str:
    return uri.rsplit("/", 1)[-1]


def discover(limit: int = 20_000, offset: int = 0) -> list[dict]:
    """Classes that have an English Wikipedia category: {"qid", "label", "category"}."""
    rows = query(DISCOVER % (ENWIKI, limit, offset))
    return [{"qid": qid(r["class"]), "label": r["classLabel"], "category": r["catTitle"]} for r in rows]


def members(class_qid: str, limit: int = 5_000) -> dict[str, int]:
    """English Wikipedia article title -> sitelink count, for every instance of
    the class or any subclass."""
    return {r["title"]: int(r["sitelinks"]) for r in query(MEMBERS % (class_qid, ENWIKI, limit))}


def sitelinks(titles: list[str], batch: int = 200) -> dict[str, int]:
    """Sitelink counts (how many language editions have the article) for
    titles that came from Wikipedia rather than Wikidata."""
    out: dict[str, int] = {}
    for i in range(0, len(titles), batch):
        values = " ".join('"%s"@en' % t.replace('"', '\\"') for t in titles[i:i + batch])
        for r in query(SITELINKS % (values, ENWIKI)):
            out[r["title"]] = int(r["sitelinks"])
    return out
