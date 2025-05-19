PYTHONPATH := $(shell pwd)/src

.PHONY: pytest

pytest:
	PYTHONPATH=$(PYTHONPATH) pytest
