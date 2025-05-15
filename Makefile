PYTHONPATH := $(shell pwd)

.PHONY: pytest tier1 tier2 tier3 tier4

pytest:
	PYTHONPATH=$(PYTHONPATH) pytest

tier1:
	PYTHONPATH=$(PYTHONPATH) pytest tests/tier1

tier2:
	PYTHONPATH=$(PYTHONPATH) pytest tests/tier2

tier3:
	PYTHONPATH=$(PYTHONPATH) pytest tests/tier3

tier4:
	PYTHONPATH=$(PYTHONPATH) pytest tests/tier4
