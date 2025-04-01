import asyncio
import json
import random
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx
import pandas as pd
from bs4 import BeautifulSoup, Tag

from config import (
    DATA_DIR,
    DEBUG_DIR,
    DEBUG_MODE,
    DEFAULT_BASE_URL,
    DEFAULT_CITY,
    MAX_RETRIES,
    REQUEST_TIMEOUT,
    RETRY_DELAY,
    setup_logging,
)

logger = setup_logging("minfin_scraper")


class MinfinExchangeRateScraper:
    """
    A scraper for bank exchange rates from minfin.com.ua.
    Uses asynchronous requests for better performance and resilience.
    """

    USER_AGENTS = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.0 Safari/605.1.15",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:95.0) Gecko/20100101 Firefox/95.0",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/94.0.4606.81 Safari/537.36",
    ]

    def __init__(self, base_url: str = DEFAULT_BASE_URL, city: str = DEFAULT_CITY):
        self.base_url = base_url
        self.city = city.lower()
        self.headers = {
            "Accept-Language": "en-US,en;q=0.9,uk;q=0.8,ru;q=0.7",
        }

        self.max_retries = MAX_RETRIES
        self.retry_delay = RETRY_DELAY
        self.request_timeout = REQUEST_TIMEOUT

        self.output_dir = DATA_DIR
        self.debug_dir = DEBUG_DIR

        # logger.info(f"Output directory: {self.output_dir}")
        # logger.info(f"Debug directory: {self.debug_dir}")

    def set_city(self, city: str) -> None:
        """Set the city for which to fetch exchange rates."""
        self.city = city.lower()
        logger.info(f"City set to: {self.city}")

    def _get_random_user_agent(self) -> str:
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

        if not DEBUG_MODE:
            return None

        filename = self.debug_dir / f"{currency}_{suffix}.{file_ext}"

        with open(filename, "w", encoding="utf-8") as f:
            f.write(str(content))

        logger.info(f"Saved debug file to {filename}")
        return filename

    def _save_debug_table(self, table: Tag, currency: str) -> Optional[Path]:
        return self._save_debug_file(table, currency, "table", "html")

    def _extract_bank_data(self, cell_values: List[str], currency: str) -> Dict[str, Any]:
        bank_name = cell_values[0]

        # Helper function to extract and validate rate values
        def extract_rate(index: int) -> Optional[str]:
            if len(cell_values) <= index:
                return None
            value = cell_values[index]
            return value if value and value != "-" else None

        # Extract rates using the helper function
        cash_buy = extract_rate(1)
        cash_sell = extract_rate(3)
        card_buy = extract_rate(4)
        card_sell = extract_rate(6)

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

    def _find_exchange_rate_table(self, soup: BeautifulSoup) -> Optional[Tag]:
        all_tables = soup.find_all("table")
        logger.info(f"Found {len(all_tables)} tables on the page")

        for i, table in enumerate(all_tables, 1):
            logger.info(f"Checking table {i}...")
            if table.get("id") == "smTable" or "mfcur-table-sm-banks" in table.get("class", []):
                logger.info(f"Found main exchange rates table (#{i})")
                return table

        logger.warning("Could not find the exchange rates table")
        return None

    def _extract_table_headers(self, table: Tag) -> Tuple[List[str], List[str]]:
        header_row = table.find("thead").find_all("tr")[0]
        header_cells = [cell.text.strip() for cell in header_row.find_all(["th", "td"])]
        logger.info(f"Header cells: {header_cells}")

        subheader_row = table.find("thead").find_all("tr")[1]
        subheader_cells = [cell.text.strip() for cell in subheader_row.find_all(["th", "td"])]
        logger.info(f"Subheader cells: {subheader_cells}")

        return header_cells, subheader_cells

    def _process_table_rows(self, table: Tag, currency: str) -> List[Dict[str, Any]]:
        data = []
        rows = table.find("tbody").find_all("tr")

        for i, row in enumerate(rows):
            cells = row.find_all(["td", "th"])
            if len(cells) < 5:  # Skip rows with insufficient data
                continue

            cell_values = [cell.text.strip() for cell in cells]

            try:
                bank_data = self._extract_bank_data(cell_values, currency)
                bank_name = bank_data["bank"]

                logger.info(
                    f"Added data for {bank_name}: "
                    f"cash {bank_data['cash_buy']}/{bank_data['cash_sell']}, "
                    f"card {bank_data['card_buy']}/{bank_data['card_sell']}, "
                    f"time {bank_data['update_time']}"
                )
                data.append(bank_data)
            except Exception as e:
                logger.error(f"Error processing row {i+3}: {e}")

        return data

    def _sort_exchange_data(self, data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        def key_func(x: Dict[str, Any]) -> float:
            try:
                return float(x.get("cash_sell", "-inf")) if x.get("cash_sell") else float("-inf")
            except (ValueError, TypeError):
                return float("-inf")

        return sorted(data, key=key_func)

    def parse_exchange_rates(self, soup: BeautifulSoup, currency: str) -> List[Dict[str, Any]]:
        logger.info(f"Looking for exchange rate table for {currency}...")

        try:
            # Find main table
            main_table = self._find_exchange_rate_table(soup)
            if not main_table:
                if DEBUG_MODE:
                    self._save_debug_file(soup, currency, "sample", "txt")
                return []

            # Save the table HTML for debugging
            self._save_debug_table(main_table, currency)

            # Extract header information
            self._extract_table_headers(main_table)

            # Process data rows
            data = self._process_table_rows(main_table, currency)

            # Sort the data
            sorted_data = self._sort_exchange_data(data)

            logger.info(f"Extracted data for {len(sorted_data)} banks")
            return sorted_data

        except Exception as e:
            logger.error(f"Error parsing table structure: {e}")
            return []

    async def get_exchange_rates(self, currency: str) -> List[Dict[str, Any]]:
        try:
            html_content = await self.fetch_page(currency)
            soup = BeautifulSoup(html_content, "lxml")
            exchange_data = self.parse_exchange_rates(soup, currency)
            return exchange_data
        except Exception as e:
            logger.error(f"Error fetching exchange rates for {currency}: {e}")
            return []

    def _create_output_filename(self, currency: str, format_type: str) -> Path:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return self.output_dir / f"{timestamp}_{currency}_exchange_rates.{format_type}"

    def _save_data_to_file(
        self, data: List[Dict[str, Any]], currency: str, format_type: str
    ) -> Optional[Path]:
        if not data:
            logger.warning(f"No data to save for {currency}")
            return None

        try:
            filename = self._create_output_filename(currency, format_type)

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


async def scrape_currency(scraper: MinfinExchangeRateScraper, currency: str) -> None:
    logger.info(f"Fetching {currency.upper()} exchange rates...")
    data = await scraper.get_exchange_rates(currency)

    if data:
        scraper.save_to_csv(data, currency)
        scraper.save_to_json(data, currency)
    else:
        logger.warning(f"No data was collected for {currency}")


async def run_scraper(currencies=None):
    if currencies is None:
        currencies = ["usd", "eur"]

    try:
        scraper = MinfinExchangeRateScraper()

        # Fetch exchange rates for multiple currencies concurrently
        await asyncio.gather(*[scrape_currency(scraper, currency) for currency in currencies])

        logger.info("Scraping completed successfully!")
        return True
    except Exception as e:
        logger.error(f"Error during scraping process: {e}")
        return False 
