#!/usr/bin/env python3
import logging
import os
from pathlib import Path

# Project structure
PROJECT_ROOT = Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_DIR = PROJECT_ROOT / "data"
DEBUG_DIR = PROJECT_ROOT / "debug"
LOGS_DIR = PROJECT_ROOT / "logs"

# Ensure directories exist
DATA_DIR.mkdir(exist_ok=True)
DEBUG_DIR.mkdir(exist_ok=True)
LOGS_DIR.mkdir(exist_ok=True)

# Application settings
DEBUG_MODE = False  # Set to True to enable debug file creation

# Scraper defaults
DEFAULT_BASE_URL = "https://minfin.com.ua/currency/banks/"
DEFAULT_CITY = "kiev"
DEFAULT_CURRENCIES = ["usd", "eur"]

# Request settings
MAX_RETRIES = 3
RETRY_DELAY = 2  # seconds
REQUEST_TIMEOUT = 30.0  # seconds


# Configure logging
def setup_logging(log_name="bank_scraper"):
    """Configure and return a logger with file and console handlers."""
    logger = logging.getLogger(log_name)

    # Clear any existing handlers
    if logger.handlers:
        logger.handlers.clear()

    # Configure root logger
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(LOGS_DIR / f"{log_name}.log"),
        ],
    )

    return logger
