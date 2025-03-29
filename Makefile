.PHONY: setup install clean scrape analyze all help format format-check

# Python binary path
PYTHON = .venv/bin/python
PIP = .venv/bin/pip

# Source directory
SRC = src

default: help

help:
	@echo "Available commands:"
	@echo "  make setup      - Create virtual environment and install dependencies"
	@echo "  make install    - Install dependencies in existing virtual environment"
	@echo "  make scrape     - Run the scraper to collect exchange rate data"
	@echo "  make analyze    - Run the analyzer to generate statistics"
	@echo "  make all        - Run scrape and analyze in sequence"
	@echo "  make clean      - Remove generated files"
	@echo "  make format     - Format code with isort and black"
	@echo "  make format-check - Check if code is properly formatted"

setup:
	@echo "Setting up virtual environment..."
	python -m venv .venv
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements.txt
	@echo "Setup complete!"


scrape:
	@echo "Running exchange rates scraper..."
	$(PYTHON) src/main.py
	@echo "Scraping complete!"

clean:
	@echo "Removing generated files..."
	rm -rf data/* debug/* logs/* reports/*
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
	rm -rf .pytest_cache .coverage htmlcov
	@echo "Clean complete!"
	
format:
	@echo "Formatting code..."
	isort --profile black $(SRC)
	black $(SRC)
	@echo "Formatting complete!"

format-check:
	@echo "Checking code format..."
	isort --profile black --check-only --diff $(SRC)
	black --check --diff $(SRC)
	@echo "Format check complete!"
