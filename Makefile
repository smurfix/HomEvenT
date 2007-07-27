#!/usr/bin/make -f

export PYTHONPATH=$(shell pwd)

all:
	@echo Nothing to do yet.
install:
	@echo Not implemented yet.
test:
	@$(MAKE) -C test --no-print-directory
i interactive:
	python test.py
p parser:
	python test.py P
d debug:
	pdb test.py

.PHONY: test i interactive
