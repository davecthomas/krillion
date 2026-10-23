# Krillion: build the question bank and run the game.
#
#   make catalog      build every raw question that has no built file yet (JOBS=3 for parallel)
#   make catalog-all  rebuild every question (after a scoring change)
#   make package      bundle the built questions into data/packages/default.jsonl.gz
#   make questions    catalog, then package: what to run after /krillion-catalog
#   make serve        run the game on http://localhost:8765
#   make test         run the tests
#
# Raw questions come from the /krillion-catalog skill (see README) and live in
# data/catalog/raw/. Building verifies answers on Wikipedia, adds members from
# Wikipedia categories and Wikidata, scores them, and writes
# data/catalog/questions/. Packaging bundles those into data/packages/, the
# committed file the game unpacks on startup and a database can import.

PACKAGE ?= default
JOBS ?= 1

.PHONY: catalog catalog-all package questions serve test lint

# JOBS=3 splits the questions across three build processes.
catalog:
	@for i in $$(seq 0 $$(($(JOBS) - 1))); do \
	  uv run python -m pipeline.catalog --shard $$i/$(JOBS) & \
	done; wait

catalog-all:
	@for i in $$(seq 0 $$(($(JOBS) - 1))); do \
	  uv run python -m pipeline.catalog --all --shard $$i/$(JOBS) & \
	done; wait

package:
	uv run python -m pipeline.package --name $(PACKAGE)

questions: catalog package

serve:
	uv run python server.py --port 8765

test:
	uv run -q pytest -q

lint:
	uvx ruff check pipeline krillion tests server.py
