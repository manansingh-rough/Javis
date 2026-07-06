# Developer shortcuts
.PHONY: install test run
install:
	pip install -r requirements.txt
run:
	python main.py
test:
	pytest tests/ -v
