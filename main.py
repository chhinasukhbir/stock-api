"""
Yahoo Finance Stock API
========================
A small FastAPI service that wraps `yfinance` to expose:
  - Current price for a ticker
  - Historical (past) price data for a ticker
  - Available option expiry dates for a ticker
  - Call option chain for a specific expiry date

Data source: Yahoo Finance (via the unofficial `yfinance` package).
"""

from datetime import datetime, timezone
from typing import Optional

import pandas as pd
import yfinance as yf
from cachetools import TTLCache
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(
    title="Yahoo Finance Stock API",
    description=(
        "Pull current price, historical price, and call option chain data "
        "for any stock ticker, sourced from Yahoo Finance."
    ),
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Simple in-memory caching to avoid hammering Yahoo Finance and to reduce the
# chance of being rate-limited. Short TTL for live price, longer for history
# and options chains (which don't change every second).
# ---------------------------------------------------------------------------
_price_cache: TTLCache = TTLCache(maxsize=512, ttl=30)
_history_cache: TTLCache = TTLCache(maxsize=512, ttl=300)
_options_meta_cache: TTLCache = TTLCache(maxsize=512, ttl=300)
_options_chain_cache: TTLCache = TTLCache(maxsize=1024, ttl=120)


def get_ticker(symbol: str) -> yf.Ticker:
    symbol = (symbol or "").strip().upper()
    if not symbol:
        raise HTTPException(status_code=400, detail="Ticker symbol is required.")
    return yf.Ticker(symbol)


def _fast_info_get(fast_info, key: str, default=None):
    """yfinance's FastInfo object supports __getitem__ but not always .get()."""
    try:
        value = fast_info[key]
        if value is None:
            return default
        return value
    except Exception:
        return default


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@app.get("/", tags=["meta"])
def root():
    return {
        "service": "Yahoo Finance Stock API",
        "status": "ok",
        "endpoints": [
            "/health",
            "/stocks/{ticker}/price",
            "/stocks/{ticker}/history",
            "/stocks/{ticker}/options",
            "/stocks/{ticker}/options/{expiry}/calls",
        ],
        "docs": "/docs",
    }


@app.get("/health", tags=["meta"])
def health():
    return {"status": "ok", "time": _now_iso()}


@app.get("/stocks/{ticker}/price", tags=["price"])
def current_price(ticker: str):
    """Latest available price for the ticker, plus change vs. previous close."""
    ticker = ticker.strip().upper()
    cached = _price_cache.get(ticker)
    if cached is not None:
        return cached

    t = get_ticker(ticker)

    price = None
    prev_close = None
    currency = None

    try:
        fast_info = t.fast_info
        price = _fast_info_get(fast_info, "lastPrice") or _fast_info_get(fast_info, "last_price")
        prev_close = _fast_info_get(fast_info, "previousClose") or _fast_info_get(fast_info, "previous_close")
        currency = _fast_info_get(fast_info, "currency")
    except Exception:
        pass

    if price is None:
        # Fall back to the most recent close from daily history.
        hist = t.history(period="5d")
        if hist.empty:
            raise HTTPException(status_code=404, detail=f"No price data found for ticker '{ticker}'.")
        price = float(hist["Close"].iloc[-1])
        if prev_close is None and len(hist) >= 2:
            prev_close = float(hist["Close"].iloc[-2])

    change = None
    change_percent = None
    if prev_close:
        change = round(float(price) - float(prev_close), 4)
        change_percent = round((change / float(prev_close)) * 100, 4)

    result = {
        "ticker": ticker,
        "price": round(float(price), 4),
        "previous_close": round(float(prev_close), 4) if prev_close else None,
        "change": change,
        "change_percent": change_percent,
        "currency": currency,
        "as_of": _now_iso(),
    }
    _price_cache[ticker] = result
    return result


@app.get("/stocks/{ticker}/history", tags=["price"])
def price_history(
    ticker: str,
    period: str = Query(
        "1mo",
        description="1d,5d,1mo,3mo,6mo,1y,2y,5y,10y,ytd,max (ignored if start is given)",
    ),
    interval: str = Query(
        "1d",
        description="1m,2m,5m,15m,30m,60m,90m,1h,1d,5d,1wk,1mo,3mo",
    ),
    start: Optional[str] = Query(None, description="Start date YYYY-MM-DD (overrides period)"),
    end: Optional[str] = Query(None, description="End date YYYY-MM-DD (optional, used with start)"),
):
    """Past price data (OHLCV) for a ticker over a period/interval or explicit date range."""
    ticker = ticker.strip().upper()
    cache_key = (ticker, period, interval, start, end)
    cached = _history_cache.get(cache_key)
    if cached is not None:
        return cached

    t = get_ticker(ticker)
    try:
        if start:
            hist = t.history(start=start, end=end, interval=interval)
        else:
            hist = t.history(period=period, interval=interval)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to fetch history for '{ticker}': {e}")

    if hist.empty:
        raise HTTPException(status_code=404, detail=f"No historical data found for ticker '{ticker}'.")

    hist = hist.reset_index()
    date_col = "Date" if "Date" in hist.columns else "Datetime"

    records = []
    for _, row in hist.iterrows():
        vol = row.get("Volume")
        records.append(
            {
                "date": row[date_col].isoformat(),
                "open": round(float(row["Open"]), 4) if pd.notna(row["Open"]) else None,
                "high": round(float(row["High"]), 4) if pd.notna(row["High"]) else None,
                "low": round(float(row["Low"]), 4) if pd.notna(row["Low"]) else None,
                "close": round(float(row["Close"]), 4) if pd.notna(row["Close"]) else None,
                "volume": int(vol) if pd.notna(vol) else None,
            }
        )

    result = {
        "ticker": ticker,
        "period": period if not start else None,
        "interval": interval,
        "start": start,
        "end": end,
        "count": len(records),
        "data": records,
    }
    _history_cache[cache_key] = result
    return result


@app.get("/stocks/{ticker}/options", tags=["options"])
def option_expiries(ticker: str):
    """List available option expiry dates for a ticker."""
    ticker = ticker.strip().upper()
    cached = _options_meta_cache.get(ticker)
    if cached is not None:
        return cached

    t = get_ticker(ticker)
    try:
        expiries = t.options
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to fetch option expiries for '{ticker}': {e}")

    if not expiries:
        raise HTTPException(status_code=404, detail=f"No options data found for ticker '{ticker}'.")

    result = {"ticker": ticker, "expiry_dates": list(expiries)}
    _options_meta_cache[ticker] = result
    return result


@app.get("/stocks/{ticker}/options/{expiry}/calls", tags=["options"])
def call_options(ticker: str, expiry: str):
    """Call option chain for a ticker at a specific expiry date (YYYY-MM-DD)."""
    ticker = ticker.strip().upper()
    cache_key = (ticker, expiry)
    cached = _options_chain_cache.get(cache_key)
    if cached is not None:
        return cached

    t = get_ticker(ticker)
    try:
        available = t.options
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to fetch option expiries for '{ticker}': {e}")

    if not available:
        raise HTTPException(status_code=404, detail=f"No options data found for ticker '{ticker}'.")

    if expiry not in available:
        raise HTTPException(
            status_code=404,
            detail=f"Expiry '{expiry}' not available for '{ticker}'. Available expiries: {list(available)}",
        )

    try:
        chain = t.option_chain(expiry)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to fetch option chain for '{ticker}' @ {expiry}: {e}")

    calls_df = chain.calls.copy()
    calls_df = calls_df.where(pd.notnull(calls_df), None)

    calls = []
    for _, r in calls_df.iterrows():
        last_trade = r.get("lastTradeDate")
        calls.append(
            {
                "contract_symbol": r.get("contractSymbol"),
                "strike": r.get("strike"),
                "last_price": r.get("lastPrice"),
                "bid": r.get("bid"),
                "ask": r.get("ask"),
                "change": r.get("change"),
                "percent_change": r.get("percentChange"),
                "volume": int(r["volume"]) if r.get("volume") is not None and pd.notna(r.get("volume")) else None,
                "open_interest": int(r["openInterest"])
                if r.get("openInterest") is not None and pd.notna(r.get("openInterest"))
                else None,
                "implied_volatility": r.get("impliedVolatility"),
                "in_the_money": bool(r.get("inTheMoney")) if r.get("inTheMoney") is not None else None,
                "last_trade_date": str(last_trade) if last_trade is not None else None,
            }
        )

    result = {
        "ticker": ticker,
        "expiry": expiry,
        "count": len(calls),
        "calls": calls,
    }
    _options_chain_cache[cache_key] = result
    return result


@app.exception_handler(Exception)
async def unhandled_exception_handler(request, exc):
    from fastapi.responses import JSONResponse

    return JSONResponse(
        status_code=500,
        content={"detail": f"Unexpected server error: {exc}"},
    )
