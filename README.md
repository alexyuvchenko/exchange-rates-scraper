# Bank Exchange Rates Scraper

A Python application for scraping bank exchange rates from financial websites.

## Features

- Asynchronous web scraping for better performance
- Supports multiple currencies (USD, EUR, etc.)
- Saves data in both CSV and JSON formats
- Debug mode for development and troubleshooting
- Command-line interface for customization

## Setup

1. Create a virtual environment and install dependencies:
   ```bash
   make setup
   ```
## Usage

Run the scraper:
```bash
python src/main.py
```
With custom options:
```bash
python src/main.py --debug --currencies usd eur
```
## Development

### Code Quality Tools

This project uses several code quality tools to maintain a consistent codebase:

1. **Black** - Code formatter
2. **isort** - Import sorter

### Makefile Commands

- Format the code:
  ```bash
  make format
  ```
- Check if code is properly formatted:
  ```bash
  make format-check
  ```
- Clean generated files:
  ```bash
  make clean
  ```
## Configuration

The application can be configured via `src/config.py` or through command-line arguments.

## Data

- Scraped data is saved to the `data` directory in both CSV and JSON formats
- Debug information is saved to the `debug` directory
- Log files are created in the `logs` directory

## Data Structure

The scraped data includes the following information for each bank:

- Bank name
- Currency (USD or EUR)
- Cash buy rate
- Cash sell rate
- Card buy rate
- Card sell rate
- Last update time

## Advanced Features

- **Asynchronous Processing**: Uses Python's asyncio for concurrent operations
- **Error Resilience**: Comprehensive error handling and retry mechanisms
- **Structured Logging**: Detailed logs for monitoring and troubleshooting
- **Type Annotations**: Full type hints for better code quality and IDE support

## Troubleshooting

If you encounter any issues with the scraper:
1. Check the log files in the `logs` directory for detailed error information
2. Examine the debug files in the `debug` directory - the application saves HTML samples and table structures to help diagnose parsing problems
3. Verify your internet connection and access to minfin.com.ua

## License

[MIT License](LICENSE)
