#!/usr/bin/env python3
import asyncio
import json
import os
import random
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

# Add the src directory to the Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import httpx
import pandas as pd
from bs4 import BeautifulSoup

from config import (
    DATA_DIR,
    DEBUG_DIR,
    DEBUG_MODE,
    DEFAULT_BASE_URL,
    DEFAULT_CITY,
    MAX_RETRIES,
    PROJECT_ROOT,
    REQUEST_TIMEOUT,
    RETRY_DELAY,
    setup_logging,
)

# Setup logger
logger = setup_logging("bank_scraper")


class BankExchangeRateScraper:
    """
    A scraper for bank exchange rates from minfin.com.ua.
    Uses asynchronous requests for better performance and resilience.
    """

    # Common user agent strings to rotate for web scraping
    USER_AGENTS = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.0 Safari/605.1.15",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:95.0) Gecko/20100101 Firefox/95.0",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/94.0.4606.81 Safari/537.36",
    ]

    def __init__(self, base_url: str = DEFAULT_BASE_URL, city: str = DEFAULT_CITY):
        """
        Initialize the scraper with base URL and city.

        Args:
            base_url: The base URL for the website
            city: The city for which to fetch exchange rates
        """
        self.base_url = base_url
        self.city = city.lower()
        self.headers = {
            "Accept-Language": "en-US,en;q=0.9,uk;q=0.8,ru;q=0.7",
        }

        # Configuration
        self.max_retries = MAX_RETRIES
        self.retry_delay = RETRY_DELAY
        self.request_timeout = REQUEST_TIMEOUT

        # Directory paths
        self.output_dir = DATA_DIR
        self.debug_dir = DEBUG_DIR

        logger.info(f"Output directory: {self.output_dir}")
        logger.info(f"Debug directory: {self.debug_dir}")

    def set_city(self, city: str) -> None:
        """Set the city for which to fetch exchange rates."""
        self.city = city.lower()
        logger.info(f"City set to: {self.city}")

    def _get_random_user_agent(self) -> str:
        """Get a random user agent from the list to avoid detection."""
        return random.choice(self.USER_AGENTS)

    async def fetch_page(self, currency: str) -> str:
        """
        Fetch HTML content from the website for a specific currency with retry mechanism.

        Args:
            currency: The currency code (e.g., "usd", "eur")

        Returns:
            The HTML content as a string

        Raises:
            ConnectionError: If the page cannot be fetched after max retries
        """
        url = f"{self.base_url}{self.city}/{currency}/"
        logger.info(f"Fetching URL: {url}")

        retries = 0
        while retries < self.max_retries:
            try:
                headers = self.headers.copy()
                headers["User-Agent"] = self._get_random_user_agent()

                async with httpx.AsyncClient(timeout=self.request_timeout) as client:
                    logger.info(f"Sending request to {url}...")
                    response = await client.get(url, headers=headers, follow_redirects=True)
                    response.raise_for_status()
                    return response.text
            except (httpx.HTTPError, httpx.NetworkError, httpx.TimeoutException) as e:
                retries += 1
                if retries < self.max_retries:
                    logger.warning(
                        f"Request failed: {e}. Retrying in {self.retry_delay} seconds... (Attempt {retries+1}/{self.max_retries})"
                    )
                    await asyncio.sleep(self.retry_delay)
                else:
                    logger.error(f"Failed to fetch data after {self.max_retries} attempts: {e}")
                    raise ConnectionError(
                        f"Failed to fetch data after {self.max_retries} attempts: {e}"
                    )

    def _save_debug_file(
        self, content: str, currency: str, suffix: str, file_ext: str = "html"
    ) -> Optional[Path]:
        """
        Generic method to save debug information to a file.

        Args:
            content: The content to save
            currency: The currency code
            suffix: A suffix for the filename
            file_ext: The file extension

        Returns:
            The path to the saved file or None if debug mode is disabled
        """
        # Skip saving debug files if DEBUG_MODE is False
        if not DEBUG_MODE:
            return None

        filename = self.debug_dir / f"{currency}_{suffix}.{file_ext}"

        with open(filename, "w", encoding="utf-8") as f:
            f.write(str(content))

        logger.info(f"Saved debug file to {filename}")
        return filename

    def _save_debug_table(self, table, currency: str) -> Optional[Path]:
        """Save a table for debugging purposes."""
        return self._save_debug_file(table, currency, "table", "html")

    def _extract_bank_data(self, cell_values: List[str], currency: str) -> Dict[str, Any]:
        """
        Extract structured bank data from table cell values.

        Args:
            cell_values: List of text values from table cells
            currency: The currency code

        Returns:
            Dictionary containing bank exchange rate data
        """
        bank_name = cell_values[0]

        # Extract cash buy and sell rates
        cash_buy = cell_values[1] if cell_values[1] and cell_values[1] != "-" else None
        cash_sell = (
            cell_values[3]
            if len(cell_values) > 3 and cell_values[3] and cell_values[3] != "-"
            else None
        )

        # Extract card buy and sell rates (if available)
        card_buy = (
            cell_values[4]
            if len(cell_values) > 4 and cell_values[4] and cell_values[4] != "-"
            else None
        )
        card_sell = (
            cell_values[6]
            if len(cell_values) > 6 and cell_values[6] and cell_values[6] != "-"
            else None
        )

        # Extract update time
        update_time = cell_values[7] if len(cell_values) > 7 else None

        return {
            "bank": bank_name,
            "currency": currency.upper(),
            "cash_buy": cash_buy,
            "cash_sell": cash_sell,
            "card_buy": card_buy,
            "card_sell": card_sell,
            "update_time": update_time,
        }

    def parse_exchange_rates(self, soup: BeautifulSoup, currency: str) -> List[Dict[str, Any]]:
        """
        Parse the exchange rates from the HTML soup.

        Args:
            soup: BeautifulSoup object containing the page HTML
            currency: The currency code

        Returns:
            List of dictionaries containing bank exchange rate data
        """
        logger.info(f"Looking for exchange rate table for {currency}...")

        all_tables = soup.find_all("table")
        logger.info(f"Found {len(all_tables)} tables on the page")

        # Find the main exchange rates table
        main_table = None
        for i, table in enumerate(all_tables, 1):
            logger.info(f"Checking table {i}...")
            if table.get("id") == "smTable" or "mfcur-table-sm-banks" in table.get("class", []):
                main_table = table
                logger.info(f"Found main exchange rates table (#{i})")
                break

        if not main_table:
            logger.warning("Could not find the exchange rates table")
            if DEBUG_MODE:
                self._save_debug_file(soup, currency, "sample", "txt")
            return []

        # Save the table HTML for debugging
        self._save_debug_table(main_table, currency)

        try:
            # Extract header information
            header_row = main_table.find("thead").find_all("tr")[0]
            header_cells = [cell.text.strip() for cell in header_row.find_all(["th", "td"])]
            logger.info(f"Header cells: {header_cells}")

            # Extract subheader information
            subheader_row = main_table.find("thead").find_all("tr")[1]
            subheader_cells = [cell.text.strip() for cell in subheader_row.find_all(["th", "td"])]
            logger.info(f"Subheader cells: {subheader_cells}")

            # Process data rows
            data = []
            rows = main_table.find("tbody").find_all("tr")

            for i, row in enumerate(rows):
                cells = row.find_all(["td", "th"])
                if len(cells) < 5:  # Skip rows with insufficient data
                    continue

                cell_values = [cell.text.strip() for cell in cells]

                try:
                    bank_data = self._extract_bank_data(cell_values, currency)
                    bank_name = bank_data["bank"]
                    cash_buy = bank_data["cash_buy"]
                    cash_sell = bank_data["cash_sell"]
                    card_buy = bank_data["card_buy"]
                    card_sell = bank_data["card_sell"]
                    update_time = bank_data["update_time"]

                    logger.info(
                        f"Added data for {bank_name}: cash {cash_buy}/{cash_sell}, card {card_buy}/{card_sell}, time {update_time}"
                    )
                    data.append(bank_data)
                except Exception as e:
                    logger.error(f"Error processing row {i+3}: {e}")

            logger.info(f"Extracted data for {len(data)} banks")
            key_func = lambda x: float(x.get("cash_sell")) if x.get("cash_sell") else float('-inf')
            data.sort(key=key_func)
            return data
        except Exception as e:
            logger.error(f"Error parsing table structure: {e}")
            return []

    async def get_exchange_rates(self, currency: str) -> List[Dict[str, Any]]:
        """
        Get exchange rates for a specific currency.

        Args:
            currency: The currency code

        Returns:
            List of dictionaries containing bank exchange rate data
        """
        try:
            html_content = await self.fetch_page(currency)
            soup = BeautifulSoup(html_content, "lxml")
            exchange_data = self.parse_exchange_rates(soup, currency)
            return exchange_data
        except Exception as e:
            logger.error(f"Error fetching exchange rates for {currency}: {e}")
            return []

    def _save_data_to_file(
        self, data: List[Dict[str, Any]], currency: str, format_type: str
    ) -> Optional[Path]:
        """
        Generic method to save data to a file.

        Args:
            data: The data to save
            currency: The currency code
            format_type: The format type ('csv' or 'json')

        Returns:
            The path to the saved file, or None if saving failed
        """
        if not data:
            logger.warning(f"No data to save for {currency}")
            return None

        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = self.output_dir / f"{timestamp}_{currency}_exchange_rates.{format_type}"

            if format_type == "csv":
                df = pd.DataFrame(data)
                df.to_csv(filename, index=False)
            elif format_type == "json":
                with open(filename, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=4)
            else:
                logger.error(f"Unsupported format type: {format_type}")
                return None

            logger.info(f"Data saved to {filename}")
            return filename
        except Exception as e:
            logger.error(f"Error saving {format_type.upper()} data: {e}")
            return None

    def save_to_csv(self, data: List[Dict[str, Any]], currency: str) -> Optional[Path]:
        """Save exchange rates data to a CSV file."""
        return self._save_data_to_file(data, currency, "csv")

    def save_to_json(self, data: List[Dict[str, Any]], currency: str) -> Optional[Path]:
        """Save exchange rates data to a JSON file."""
        return self._save_data_to_file(data, currency, "json")


async def scrape_currency(scraper: BankExchangeRateScraper, currency: str) -> None:
    """
    Helper function to scrape a specific currency.

    Args:
        scraper: The scraper instance
        currency: The currency code
    """
    logger.info(f"Fetching {currency.upper()} exchange rates...")
    data = await scraper.get_exchange_rates(currency)

    if data:
        scraper.save_to_csv(data, currency)
        scraper.save_to_json(data, currency)
    else:
        logger.warning(f"No data was collected for {currency}")


async def run_scraper(currencies=None):
    """
    Run the scraper for specified currencies.

    Args:
        currencies: List of currency codes to scrape (defaults to USD and EUR)

    Returns:
        True if scraping was successful, False otherwise
    """
    if currencies is None:
        currencies = ["usd", "eur"]

    try:
        scraper = BankExchangeRateScraper()

        # Fetch exchange rates for multiple currencies concurrently
        await asyncio.gather(*[scrape_currency(scraper, currency) for currency in currencies])

        logger.info("Scraping completed successfully!")
        return True
    except Exception as e:
        logger.error(f"Error during scraping process: {e}")
        return False
