.PHONY: install lint linecount typecheck test coverage phase-metrics phase46 phase79 ci

PYTHON ?= python

install:
	$(PYTHON) -m pip install -e ".[dev]"

lint:
	$(PYTHON) -m ruff check .

linecount:
	$(PYTHON) scripts/check_line_limit.py

typecheck:
	$(PYTHON) scripts/typecheck.py

test:
	$(PYTHON) -m pytest

coverage:
	$(PYTHON) -m coverage run -m pytest
	$(PYTHON) -m coverage report

phase-metrics:
	$(PYTHON) scripts/phase_metrics.py

phase46:
	$(PYTHON) scripts/run_replay.py
	$(PYTHON) scripts/generate_scenarios.py
	$(PYTHON) scripts/run_rule_baseline.py
	$(PYTHON) scripts/phase46_metrics.py

phase79:
	$(PYTHON) scripts/generate_scenarios.py --count 600 --events-per-scenario 30 --clean
	$(PYTHON) scripts/run_benchmark.py
	$(PYTHON) scripts/train_order_mtpp.py
	$(PYTHON) scripts/train_order_s2p2.py
	$(PYTHON) scripts/phase79_metrics.py

ci: lint linecount typecheck test coverage phase-metrics
