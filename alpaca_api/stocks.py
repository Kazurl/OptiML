"""
Check API references at: "https://docs.alpaca.markets/reference/stockbars"
Scroll through the sidebar for various market data api

For Historical and live data on stocks, crypto, options:
alpaca.data.historical

For realtime (live) data streaming:
alpaca.data.live

For specifc data (bars, trades, quotes):
alpaca.data.requests
alpaca.data.timeframe
    - to specify "1Min", "1Hour", "1Day"
"""
from dotenv import load_dotenv
import os

from alpaca.data import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
import datetime
import pandas as pd

load_dotenv()

"""
Only takes into account daily, weekly, monthly
"""
def get_single_current_price(
    symbol: str,  # ticker i.e AAPL
    start: datetime.date,  # start date of date window
    end: datetime.date,  # end date of date window
    timeframe: TimeFrame = TimeFrame.Day
) -> float:
    client = StockHistoricalDataClient(os.getenv("ALPACA_API_KEY"), os.getenv("ALPACA_API_SECRET"))
    req_params = StockBarsRequest(
        symbol_or_symbols=symbol,
        timeframe=timeframe,
        start=start,
        end=end
    )

    # get latest closing price for ticker
    bars = client.get_stock_bars(req_params)
    return bars.df["close"].iloc[-1]

def get_recent_stock_prices(
    symbol: str,
    start_date: datetime.date,
    end_date: datetime.date
) -> pd.Series:
    """
    Fetches daily closing stock prices from Alpaca between start_date and end_date.
    Returns a pandas Series of prices indexed by date (DateTimeIndex).
    """
    client = StockHistoricalDataClient(os.getenv("ALPACA_API_KEY"), os.getenv("ALPACA_API_SECRET"))
    req_params = StockBarsRequest(
        symbol_or_symbols=symbol,
        timeframe=TimeFrame.Day,
        start=start_date.strftime("%Y-%m-%d"),
        end=end_date.strftime("%Y-%m-%d")
    )
    bars = client.get_stock_bars(req_params)
    prices = bars.df["close"]
    # Convert index to datetime if not already
    if isinstance(prices.index, pd.MultiIndex):
        prices.index = prices.index.get_level_values("timestamp")
    prices.index = pd.to_datetime(prices.index)

    return prices