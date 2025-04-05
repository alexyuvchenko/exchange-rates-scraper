import asyncio
import json
import os
import sys
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import streamlit as st

# Add the src directory to the Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from bots.telegram.streamlit_bot import (
    bot_state,
    broadcast_message,
    get_bot_status,
    get_latest_rates,
    run_bot_thread,
    stop_bot_thread,
)
from config import TELEGRAM_BOT_TOKEN, setup_logging
from scrapers.minfin_scraper import MinfinExchangeRateScraper

# Setup logger
logger = setup_logging("streamlit_app")

# Cache duration in seconds
CACHE_DURATION = 300  # 5 minutes


def init_session_state():
    """Initialize Streamlit session state variables."""
    if "rates_cache" not in st.session_state:
        st.session_state.rates_cache = None
        st.session_state.rates_timestamp = None

    if "bot_started" not in st.session_state:
        st.session_state.bot_started = False


async def fetch_rates(currencies: List[str], city: str) -> List[Dict[str, Any]]:
    """
    Fetch exchange rates for selected currencies and city.

    Args:
        currencies: List of currency codes to fetch
        city: City name for rate lookup

    Returns:
        List of exchange rate dictionaries
    """
    scraper = MinfinExchangeRateScraper(city=city)
    results = []

    for currency in currencies:
        try:
            rates = await scraper.get_exchange_rates(currency)
            if rates:
                results.extend(rates)
        except Exception as e:
            st.error(f"Error scraping {currency.upper()}: {str(e)}")
            logger.error(f"Error fetching rates for {currency}: {e}")

    return results


def update_rates_cache(rates: List[Dict[str, Any]]) -> None:
    """
    Update the rates cache in session state.

    Args:
        rates: List of exchange rate dictionaries to cache
    """
    st.session_state.rates_cache = rates
    st.session_state.rates_timestamp = datetime.now()


def is_cache_valid() -> bool:
    """
    Check if the current rates cache is valid.

    Returns:
        True if cache is valid, False otherwise
    """
    if not st.session_state.rates_cache or not st.session_state.rates_timestamp:
        return False

    age = datetime.now() - st.session_state.rates_timestamp
    return age.total_seconds() < CACHE_DURATION


def format_rates_message(rates: List[Dict[str, Any]]) -> str:
    """
    Format exchange rates into a message for sharing.

    Args:
        rates: List of exchange rate dictionaries

    Returns:
        Formatted message string
    """
    if not rates:
        return "No exchange rate data available."

    # Group rates by currency
    by_currency = {}
    for rate in rates:
        currency = rate["currency"]
        if currency not in by_currency:
            by_currency[currency] = []
        by_currency[currency].append(rate)

    # Find best rates for each currency
    message = "💰 Current Exchange Rates (Best Rates):\n\n"

    for currency, currency_rates in by_currency.items():
        # Sort by cash sell rate (ascending)
        best_rates = sorted(
            [r for r in currency_rates if r.get("cash_sell")],
            key=lambda x: float(x["cash_sell"]) if x["cash_sell"] else float("inf"),
        )

        if best_rates:
            best_rate = best_rates[0]
            message += f"{currency}:\n"
            message += f"🏦 {best_rate['bank']}\n"
            message += f"Cash: Buy {best_rate['cash_buy']} / Sell {best_rate['cash_sell']} UAH\n"

            if best_rate.get("card_buy") and best_rate.get("card_sell"):
                message += (
                    f"Card: Buy {best_rate['card_buy']} / Sell {best_rate['card_sell']} UAH\n"
                )

            message += "\n"

    return message


def render_exchange_rates_tab():
    """Render the Exchange Rates tab content."""
    st.title("Minfin Exchange Rates")
    st.write("This app scrapes exchange rates from Minfin.com.ua and displays them in a table.")

    # Sidebar for inputs
    st.sidebar.header("Scraper Options")
    city = st.sidebar.selectbox("City:", ["Kyiv", "Lviv", "Odesa", "Dnipro", "Kharkiv"], index=0)

    # Convert city name to lowercase for API
    city_for_api = city.lower()

    # Choose currencies
    selected_currencies = st.sidebar.multiselect(
        "Select currencies to display:", ["USD", "EUR", "GBP", "PLN"], default=["USD", "EUR"]
    )

    # Convert to lowercase for API
    currencies_for_api = [currency.lower() for currency in selected_currencies]

    # Create container for results
    results_container = st.container()

    # Refresh button
    if st.sidebar.button("Refresh Exchange Rates"):
        with st.spinner("Fetching exchange rates..."):
            try:
                # Run the async function to get the rates
                results = asyncio.run(fetch_rates(currencies_for_api, city_for_api))

                if results:
                    update_rates_cache(results)
                else:
                    st.warning("No exchange rate data retrieved. Please try again.")

            except Exception as e:
                st.error(f"An error occurred: {str(e)}")
                logger.error(f"Error refreshing rates: {e}")

    # Display rates (either from cache or fetch new ones)
    with results_container:
        if not is_cache_valid():
            with st.spinner("Fetching exchange rates..."):
                try:
                    results = asyncio.run(fetch_rates(currencies_for_api, city_for_api))

                    if results:
                        update_rates_cache(results)
                except Exception as e:
                    st.error(f"An error occurred: {str(e)}")
                    logger.error(f"Error fetching rates: {e}")

        # Display results from cache
        if st.session_state.rates_cache:
            display_exchange_rates(st.session_state.rates_cache, selected_currencies, city)


def display_exchange_rates(results: List[Dict[str, Any]], currencies: List[str], city: str):
    """
    Display exchange rates in a formatted table.

    Args:
        results: List of exchange rate dictionaries
        currencies: List of currencies to display
        city: City name for display
    """
    # Convert to DataFrame for better display
    df = pd.DataFrame(results)

    # Add timestamp
    timestamp = st.session_state.rates_timestamp.strftime("%Y-%m-%d %H:%M:%S")
    st.info(f"Data last updated at {timestamp}")

    # Display results grouped by currency
    for currency in currencies:
        st.subheader(f"{currency} Exchange Rates in {city}")
        currency_df = df[df["currency"] == currency.upper()]

        if not currency_df.empty:
            # Sort by cash sell rate
            currency_df = currency_df.copy()
            try:
                currency_df["cash_sell_num"] = pd.to_numeric(
                    currency_df["cash_sell"], errors="coerce"
                )
                currency_df = currency_df.sort_values("cash_sell_num")
                currency_df = currency_df.drop("cash_sell_num", axis=1)
            except Exception:
                pass  # If conversion fails, show unsorted

            # Reorder columns for better presentation
            cols = ["bank", "cash_buy", "cash_sell", "card_buy", "card_sell", "update_time"]
            st.dataframe(currency_df[cols], use_container_width=True)
        else:
            st.warning(f"No data found for {currency}")


def render_bot_tab():
    """Render the Telegram Bot tab content."""
    st.title("Telegram Bot")

    # Get bot info
    status = get_bot_status()

    # Bot status section
    st.subheader("Bot Status")

    # Show a warning if no bot token is configured
    if not status.get("token_configured", False):
        st.warning("⚠️ Telegram Bot Token is not configured! Please set it in the Settings tab.")

    # Status columns
    col1, col2, col3 = st.columns(3)

    with col1:
        if status["is_running"]:
            st.success("Bot is RUNNING", icon="✅")
        else:
            st.error("Bot is STOPPED", icon="❌")

    with col2:
        st.metric("Active Subscribers", status["subscriber_count"])

    with col3:
        render_bot_controls(status)

    # Subscription Management
    st.subheader("Subscriber Management")

    # Display subscribers
    if status["subscriber_count"] > 0:
        render_subscribers_list()
    else:
        st.info("No subscribers yet. Users can subscribe by sending /subscribe to your bot.")

    # Broadcast message feature
    render_broadcast_section(status)

    # Bot usage instructions
    render_bot_usage_instructions()


def render_bot_controls(status: Dict[str, Any]):
    """
    Render the bot control buttons.

    Args:
        status: Bot status dictionary
    """
    if status["is_running"]:
        if st.button("Stop Bot"):
            stop_bot_thread()
            st.session_state.bot_started = False
            st.rerun()
    else:
        if st.button("Start Bot", disabled=not status.get("token_configured", False)):
            run_bot_thread()
            st.session_state.bot_started = True
            time.sleep(1)  # Give bot time to start
            st.rerun()


def render_subscribers_list():
    """Render the list of subscribers in an expandable section."""
    with st.expander("View Subscribers", expanded=True):
        subscribers_data = []
        for user_id, data in bot_state.subscriptions.items():
            subscribers_data.append(
                {
                    "User ID": user_id,
                    "Username": data.get("username", "Unknown"),
                    "Subscribed Since": datetime.fromtimestamp(
                        data.get("subscribed_at", 0)
                    ).strftime("%Y-%m-%d"),
                    "Currencies": ", ".join(data.get("currencies", [])),
                }
            )

        st.dataframe(pd.DataFrame(subscribers_data), use_container_width=True)


def render_broadcast_section(status: Dict[str, Any]):
    """
    Render the broadcast message section.

    Args:
        status: Bot status dictionary
    """
    st.subheader("Send Message to Subscribers")

    broadcast_text = st.text_area(
        "Message text:",
        placeholder="Enter your message to broadcast to all subscribers...",
        disabled=not status["is_running"] or status["subscriber_count"] == 0,
    )

    send_col1, send_col2 = st.columns([1, 2])

    with send_col1:
        if st.button(
            "Send Message",
            disabled=not status["is_running"]
            or not broadcast_text
            or status["subscriber_count"] == 0,
        ):
            with st.spinner("Sending message to subscribers..."):
                sent_count = broadcast_message(broadcast_text)
                if sent_count > 0:
                    st.success(f"Message sent to {sent_count} subscribers!")
                else:
                    st.error("Failed to send message.")

    # Share latest rates with subscribers
    with send_col2:
        if st.button(
            "Share Latest Rates",
            disabled=not status["is_running"] or status["subscriber_count"] == 0,
        ):
            share_latest_rates()


def share_latest_rates():
    """Share the latest exchange rates with subscribers."""
    with st.spinner("Fetching and sharing rates..."):
        try:
            # Get the latest rates and format them as a message
            rates = get_latest_rates()
            if not rates:
                st.error("Failed to fetch rates.")
            else:
                # Format and send message
                message = format_rates_message(rates)
                sent_count = broadcast_message(message)

                if sent_count > 0:
                    st.success(f"Rates shared with {sent_count} subscribers!")
                else:
                    st.error("Failed to share rates.")
        except Exception as e:
            st.error(f"Error sharing rates: {str(e)}")
            logger.error(f"Error sharing rates: {e}")


def render_bot_usage_instructions():
    """Render instructions for using the Telegram bot."""
    st.subheader("Bot Usage")
    st.write(
        """
    To use the Telegram bot:
    
    1. Search for your bot on Telegram using its username
    2. Start a conversation with the bot by sending `/start`
    3. Use the following commands:
        - `/help` - Show available commands
        - `/rates` - Get current exchange rates
        - `/subscribe` - Subscribe to daily updates
        - `/unsubscribe` - Unsubscribe from updates
        - `/status` - Check bot status
    """
    )


def render_settings_tab():
    """Render the Settings tab content."""
    st.title("Settings")

    # Bot configuration
    render_bot_configuration()

    # Data settings
    render_data_settings()


def render_bot_configuration():
    """Render the bot configuration section."""
    st.subheader("Telegram Bot Configuration")

    # Show the current bot token (masked for security)
    current_token = TELEGRAM_BOT_TOKEN
    if current_token:
        masked_token = current_token[:4] + "..." + current_token[-4:]
        st.info(f"Current bot token: {masked_token}")
    else:
        st.warning("No bot token configured. The bot will not work without a valid token.")

    # Input for setting the bot token
    with st.form("bot_settings"):
        new_token = st.text_input(
            "Bot Token:",
            placeholder="Enter your Telegram Bot token...",
            help="You can get a token by messaging @BotFather on Telegram",
        )

        submit = st.form_submit_button("Save Settings")

        if submit and new_token:
            # This is just for demonstration - in a real app, you'd use a more secure method
            st.success("Bot token updated! Please restart the bot to apply changes.")
            # In a real app, you'd update the token in a secure way and restart the bot
            time.sleep(1)
            st.rerun()


def render_data_settings():
    """Render the data settings section."""
    st.subheader("Data Storage Settings")

    # Option to clear subscription data
    if st.button("Clear All Subscriptions"):
        bot_state.subscriptions = {}
        bot_state.save_subscriptions()
        st.success("All subscription data cleared!")
        time.sleep(1)
        st.rerun()


def main():
    """Main function to set up and run the Streamlit app."""
    # Page configuration
    st.set_page_config(
        page_title="Minfin Exchange Rates",
        page_icon="💱",
        layout="wide",
    )

    # Initialize session state
    init_session_state()

    # Create tabs
    tab1, tab2, tab3 = st.tabs(["Exchange Rates", "Telegram Bot", "Settings"])

    # Render each tab
    with tab1:
        render_exchange_rates_tab()

    with tab2:
        render_bot_tab()

    with tab3:
        render_settings_tab()

    # Start the bot automatically when the app loads
    if not st.session_state.bot_started and not bot_state.is_running and TELEGRAM_BOT_TOKEN:
        run_bot_thread()
        st.session_state.bot_started = True

    # Information about the app
    st.sidebar.markdown("---")
    st.sidebar.info(
        "This app provides real-time currency exchange rates from Minfin.com.ua and a Telegram bot interface. "
        "The bot allows users to subscribe to rate updates and check current rates directly in Telegram."
    )


if __name__ == "__main__":
    main()
