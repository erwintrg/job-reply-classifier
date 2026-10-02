PYTHON ?= python3

.PHONY: demo test install watch dry-run

demo:            ## offline demo, no installs or keys needed
	$(PYTHON) demo.py

install:         ## local venv with the Anthropic SDK and pytest
	$(PYTHON) -m venv .venv
	.venv/bin/pip install -e ".[anthropic,dev]"

test:
	$(PYTHON) -m pytest -q

dry-run:         ## one real cycle from .env, print only, nothing written
	$(PYTHON) -m job_reply_classifier --dry-run

watch:           ## run forever, one cycle every POLL_SECONDS
	$(PYTHON) -m job_reply_classifier --loop
