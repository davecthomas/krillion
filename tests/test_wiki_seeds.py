import random

from pipeline import wiki


def test_seeds_come_from_north_american_lists_and_english_articles(monkeypatch):
    urls = []

    def fake_get_json(url):
        urls.append(url)
        return {"items": [{"articles": [
            {"article": "Main_Page", "project": "en.wikipedia"},
            {"article": "Special:Search", "project": "en.wikipedia"},
            {"article": "Tater_tots", "project": "en.wikipedia"},
            {"article": "Poutine", "project": "en.wikipedia"},
            {"article": "Wikipedia:Portada", "project": "es.wikipedia"},
            {"article": "Kartoffel", "project": "de.wikipedia"},
        ]}]}

    monkeypatch.setattr(wiki, "get_json", fake_get_json)
    seeds = wiki.popular_seeds(n=10, days=4, rng=random.Random(1))
    assert sorted(seeds) == ["Poutine", "Tater tots"]
    assert len(urls) == 4
    assert all("/top-per-country/US/" in u or "/top-per-country/CA/" in u for u in urls)
