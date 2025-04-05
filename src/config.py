#!/usr/bin/env python3
import logging
import os
from pathlib import Path

from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Project structure
PROJECT_ROOT = Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_DIR = PROJECT_ROOT / "data"
DEBUG_DIR = PROJECT_ROOT / "debug"

# Ensure directories exist
DATA_DIR.mkdir(exist_ok=True)
DEBUG_DIR.mkdir(exist_ok=True)

DEBUG_MODE = os.getenv("DEBUG", "False").lower() in ("true", "1", "t", "yes")

# Scraper defaults
DEFAULT_BASE_URL = "https://minfin.com.ua/currency/banks/"
DEFAULT_CITY = "kiev"
DEFAULT_CURRENCIES = ["usd", "eur"]

# Request settings
MAX_RETRIES = 3
RETRY_DELAY = 2  # seconds
REQUEST_TIMEOUT = 30.0  # seconds

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")


# Configure logging
def setup_logging(log_name="bank_scraper"):
    """
    Configure and return a logger with console handler.

    Args:
        log_name: Name for the logger

    Returns:
        Configured logger
    """
    logger = logging.getLogger(log_name)

    log_level = logging.DEBUG if DEBUG_MODE else logging.INFO
    logger.setLevel(log_level)

    # Clear existing handlers
    if logger.handlers:
        logger.handlers.clear()

    # Create formatter
    formatter = logging.Formatter(
        "%(asctime)s - %(threadName)s - %(name)s - %(levelname)s - %(lineno)d %(message)s  %(funcName)s"
    )

    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(log_level)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    logger.info(f"Console logging initialized: {log_name} (level: {log_level})")

    return logger
