"""
MCP server exposing stock data (price, history, options) as tools Claude can
call directly - no URL pasting required, unlike the plain REST API.

Reuses the same yfinance calls as main.py, just exposed through the MCP
protocol instead of plain HTTP endpoints.
"""

import os
from mcp.server.fastmcp import FastMCP
import yfinance as yf

mcp = FastMCP("Stock Data Server")


@mcp.tool()
def get_stock_price(ticker: str) -> dict:
    """Get the current price and daily change for a stock ticker (e.g. AAPL, NBIS)."""
    stock = yf.Ticker(ticker)
    info = stock.fast_info
    change = info.last_price - info.previous_close
    return {
        "ticker": ticker.upper(),
        "price": round(info.last_price, 4),
        "previous_close": round(info.previous_close, 4),
        "change": round(change, 4),
        "change_percent": round(change / info.previous_close * 100, 4),
        "currency": info.currency,
    }


@mcp.tool()
def get_stock_history(ticker: str, period: str = "6mo") -> dict:
    """
    Get historical daily OHLCV data for a stock ticker.
    period examples: 1mo, 3mo, 6mo, 1y, 2y, 5y, max
    """
    stock = yf.Ticker(ticker)
    hist = stock.history(period=period)
    return {
        "ticker": ticker.upper(),
        "period": period,
        "count": len(hist),
        "data": [
            {
                "date": str(idx.date()),
                "open": round(row["Open"], 4),
                "high": round(row["High"], 4),
                "low": round(row["Low"], 4),
                "close": round(row["Close"], 4),
                "volume": int(row["Volume"]),
            }
            for idx, row in hist.iterrows()
        ],
    }


@mcp.tool()
def get_options_expirations(ticker: str) -> dict:
    """Get available options expiration dates for a stock ticker."""
    stock = yf.Ticker(ticker)
    return {"ticker": ticker.upper(), "expirations": list(stock.options)}


@mcp.tool()
def get_options_chain(ticker: str, expiry: str) -> dict:
    """
    Get the options chain (calls and puts) for a specific expiry date.
    expiry format: YYYY-MM-DD (use get_stock_options_expirations first to see valid dates)
    """
    stock = yf.Ticker(ticker)
    chain = stock.option_chain(expiry)
    return {
        "ticker": ticker.upper(),
        "expiry": expiry,
        "calls": chain.calls.to_dict(orient="records"),
        "puts": chain.puts.to_dict(orient="records"),
    }


if __name__ == "__main__":
    # Render (and most PaaS hosts) inject the port to bind via $PORT
    port = int(os.environ.get("PORT", 8000))
    mcp.settings.host = "0.0.0.0"
    mcp.settings.port = port
    # Streamable HTTP handles both GET and POST on one path - matches what
    # the connecting client is actually requesting (confirmed via Render logs)
    mcp.settings.streamable_http_path = "/"
    mcp.run(transport="streamable-http")
