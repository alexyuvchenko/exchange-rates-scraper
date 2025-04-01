import argparse
import asyncio
import os
import sys

# Add the src directory to the Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config
from config import DEFAULT_CURRENCIES, setup_logging
from scraper import run_scraper


# Parse command line arguments
def parse_args():
    parser = argparse.ArgumentParser(description="Bank Exchange Rates Scraper")
    parser.add_argument("--debug", action="store_true", help="Enable debug mode")
    parser.add_argument(
        "--currencies",
        nargs="+",
        default=DEFAULT_CURRENCIES,
        help=f'Currencies to scrape (default: {" ".join(DEFAULT_CURRENCIES)})',
    )
    return parser.parse_args()


# Setup logger
logger = setup_logging("bank_scraper_main")


async def run_pipeline(currencies=None, debug_mode=False):
    """
    Run the full scraping pipeline.

    Args:
        currencies: List of currency codes to scrape (defaults to USD and EUR)
        debug_mode: Whether to enable debug mode

    Returns:
        True if the pipeline completed successfully, False otherwise
    """
    if currencies is None:
        currencies = DEFAULT_CURRENCIES

    # Set debug mode
    config.DEBUG_MODE = debug_mode
    if debug_mode:
        logger.info("Debug mode enabled - debug files will be created")

    print("=" * 60)
    print("BANK EXCHANGE RATES SCRAPER")
    print("=" * 60)

    # Run the scraper
    print(f"\nRunning the scraper to fetch exchange rates for: {', '.join(currencies).upper()}")
    scraper_success = await run_scraper(currencies)

    if not scraper_success:
        logger.error("Scraper failed.")
        return False

    print("\n" + "=" * 60)
    print("Scraping completed!")
    print("=" * 60)

    return True


async def main_async(args):
    """Async main function."""
    try:
        success = await run_pipeline(currencies=args.currencies, debug_mode=args.debug)
        return 0 if success else 1
    except Exception as e:
        logger.error(f"Unhandled exception in main: {e}", exc_info=True)
        return 1


def main():
    """Main entry point."""
    args = parse_args()

    try:
        return asyncio.run(main_async(args))
    except KeyboardInterrupt:
        logger.info("Process interrupted by user")
        return 130  # Standard exit code for SIGINT
    except Exception as e:
        logger.critical(f"Critical error in main: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
