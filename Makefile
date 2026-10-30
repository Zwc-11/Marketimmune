# Every command the project needs, in pipeline order. Windows: .\make.ps1 <target>.
PYTHON ?= python
COIN   ?= SOL
DATES  ?= 20251201..20251231

.PHONY: help install lint typecheck test coverage rust-test rust-lint bench wheel \
        frontend-test frontend-build server ci \
        download-albers download-binance albers-month train

help:  ## list targets
	@grep -E '^[a-z0-9-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-18s %s\n", $$1, $$2}'

install:  ## editable install with training, server and dev extras
	$(PYTHON) -m pip install -e ".[training,server,aws,dev]"

lint:  ## ruff + 1000-line limit
	$(PYTHON) -m ruff check .
	$(PYTHON) scripts/check_line_limit.py

typecheck:  ## mypy --strict on the package
	$(PYTHON) scripts/typecheck.py

test:  ## Python tests
	$(PYTHON) -m pytest

coverage:  ## Python tests with the coverage gate
	$(PYTHON) -m coverage run -m pytest
	$(PYTHON) -m coverage report

rust-test:  ## Rust tests in release mode (includes the proptests)
	cargo test --workspace --release

rust-lint:  ## rustfmt + clippy
	cargo fmt --all --check
	cargo clippy --workspace --all-targets -- -D warnings

bench:  ## pipeline speed (Python) and order-book replay (Rust) benchmarks
	$(PYTHON) eval/pipeline_speed/bench.py --out eval/pipeline_speed/results.json
	cargo bench -p hl-replay --bench replay

wheel:  ## build the hl_replay Python extension
	maturin build --release -m crates/hl-replay-py/Cargo.toml --out dist

frontend-test:  ## frontend typecheck + unit tests
	npm --prefix frontend run typecheck
	npm --prefix frontend test

frontend-build:  ## build the terminal and copy it to server/api/static/terminal
	npm --prefix frontend run build:server

server:  ## run the Django API and the built terminal on :8000
	$(PYTHON) server/manage.py migrate
	$(PYTHON) server/manage.py runserver

ci: lint typecheck coverage rust-lint rust-test frontend-test  ## everything CI runs

download-albers:  ## Albers Dec 2025 L4 dataset (~166 GB, resumable)
	$(PYTHON) -m marketimmune.cli.download_albers --dest data/bronze/albers --set needed

download-binance:  ## Binance aggTrades for the Albers month (CEX-gap feature)
	$(PYTHON) -m marketimmune.cli.download_binance aggtrades $(COIN)USDT 2025-12-01 2025-12-31

albers-month:  ## Silver L2 + fills + Gold for COIN over DATES from the Albers archives
	$(PYTHON) -m marketimmune.cli.run_albers_month --coin $(COIN) --dates $(DATES)

train:  ## CatBoost markout model on COIN over DATES
	$(PYTHON) -m marketimmune.cli.train --coin $(COIN) --dates $(DATES)
