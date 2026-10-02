# Common tasks. `make help` lists them.
#
# Why a Makefile when there is no build step: these are the commands I actually
# run, and typing them wrong wastes the first 30 seconds of every session. One
# `make test` is worth more than a badge in a README.

PYTHON ?= python
PORT   ?= 8000

.PHONY: help
help:  ## List available targets
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

.PHONY: install
install:  ## Install dependencies
	$(PYTHON) -m pip install -r requirements.txt

.PHONY: train
train:  ## Train the ML tier and print both accuracy numbers
	$(PYTHON) train.py

.PHONY: test
test:  ## Run the test suite (offline, ~2s)
	$(PYTHON) -m pytest tests/ -q

.PHONY: run
run:  ## Start the API and UI on PORT (default 8000)
	$(PYTHON) -m uvicorn src.api:app --reload --port $(PORT)

.PHONY: check
check: test  ## Run tests, then print a demo batch through the real pipeline
	$(PYTHON) -m uvicorn src.api:app --port $(PORT) & 	sleep 5 && 	$(PYTHON) -c "import json,urllib.request; \
	  p=json.load(open('data/demo_batch.json')); \
	  r=urllib.request.Request('http://127.0.0.1:$(PORT)/classify/batch', \
	     data=json.dumps(p).encode(), headers={'Content-Type':'application/json'}); \
	  d=json.load(urllib.request.urlopen(r, timeout=300)); \
	  print('lines', d['total_lines'], d['tier_counts']); \
	  print('cost  \$$%.6f  avoided %.2f%%' % (d['total_cost_usd'], d['cost_avoided_pct'])); \
	  print('incidents', len(d['incidents']))" ; \
	kill %1

.PHONY: docker
docker:  ## Build and run in Docker
	docker compose up --build

.PHONY: clean
clean:  ## Remove caches and the local database
	rm -rf __pycache__ .pytest_cache logs.db
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
