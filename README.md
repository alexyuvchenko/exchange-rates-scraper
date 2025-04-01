# Bank Exchange Rates Scraper & Telegram Bot

A Python application for scraping bank exchange rates from financial websites and sending updates via Telegram.

## Features

- **Exchange Rate Scraper**:
  - Asynchronous web scraping for better performance
  - Supports multiple currencies (USD, EUR, etc.)
  - Saves data in both CSV and JSON formats
  - Debug mode for development and troubleshooting

- **Telegram Bot**:
  - Get instant exchange rate updates via Telegram
  - Subscribe to daily or weekly exchange rate notifications
  - Customize which currencies to track
  - Set preferred notification time

## Setup

1. Create a virtual environment and install dependencies:
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # On Windows, use: .venv\Scripts\activate
   pip install -r requirements.txt
   ```

2. For the Telegram bot, you need to:
   - Create a bot via [BotFather](https://t.me/botfather) on Telegram
   - Copy the bot token
   - Create a `.env` file in the project root (use `.env.example` as a template)
   - Add your bot token to the `.env` file

## Usage

### Running the Scraper

Basic scraper execution:
```bash
python src/main.py
```

With custom options:
```bash
python src/main.py --debug --currencies usd eur
```

### Running the Telegram Bot

Start the Telegram bot:
```bash
python src/main.py --mode bot
```

With debug mode:
```bash
python src/main.py --mode bot --debug
```

### Bot Commands for Users

Once the bot is running, users can interact with it using these commands:

- `/start` or `/help` - Get help information
- `/rates` - Get current exchange rates
- `/subscribe` - Set up daily/weekly notifications
- `/unsubscribe` - Cancel notifications
- `/settings` - View current subscription settings

## Data Structure

The scraped data includes the following information for each bank:

- Bank name
- Currency (USD or EUR)
- Cash buy rate
- Cash sell rate
- Card buy rate
- Card sell rate
- Last update time

## Directories

- `data/` - Scraped data in CSV and JSON formats, also subscription data
- `debug/` - Debug information when run in debug mode
- `logs/` - Log files for monitoring and troubleshooting
- `src/` - Source code

## Advanced Features

- **Asynchronous Processing**: Uses Python's asyncio for concurrent operations
- **Error Resilience**: Comprehensive error handling and retry mechanisms
- **Structured Logging**: Detailed logs for monitoring and troubleshooting
- **Type Annotations**: Full type hints for better code quality and IDE support

## Troubleshooting

If you encounter any issues:
1. Check the log files in the `logs` directory for detailed error information
2. Examine the debug files in the `debug` directory - these are created when running with `--debug`
3. Verify your internet connection and access to minfin.com.ua
4. For the Telegram bot, ensure your bot token is correctly configured

## License

[MIT License](LICENSE)
