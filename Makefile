# Makefile for rss-books

.PHONY: all setup test format lint start clean

# Setup virtual environment and install dependencies
setup:
	python3 -m venv venv
	. venv/bin/activate && pip install -r requirements.txt

# Run tests
test:
	. venv/bin/activate && pytest

# Format code
format:
	. venv/bin/activate && black src tests

# Lint code
lint:
	. venv/bin/activate && ruff src tests

# Run the application
start:
	. venv/bin/activate && python3 src/rss_books/main.py

# Clean up
clean:
	rm -rf venv
	rm -f output.html
	find . -type f -name '*.pyc' -delete
	find . -type d -name '__pycache__' -delete
