from alpaca.data.timeframe import TimeFrame
from unittest.mock import patch, MagicMock
import datetime
import pandas as pd
from alpaca_api.stocks import get_recent_stock_prices, get_single_current_price

@patch("alpaca_api.stocks.StockHistoricalDataClient")
def test_valid_get_single_current_price(mock_StockHistoricalDataClient) -> float:
    # set up mock
    mock_client = MagicMock()
    mock_StockHistoricalDataClient.return_value = mock_client

    # simulate df with "close" col
    df = pd.DataFrame({ "close": [100.5, 101.2, 102.0] })
    mock_bars = MagicMock()
    mock_bars.df = df
    mock_client.get_stock_bars.return_value = mock_bars

    # call function
    result = get_single_current_price(
        symbol="AAPL",
        start=datetime.date(2025, 8, 1),
        end=datetime.datetime(2025, 8, 10)
    )

    assert result == 102.0

@patch('alpaca_api.stocks.StockHistoricalDataClient')
def test_valid_get_recent_stock_prices(mock_StockHistoricalDataClient):
    mock_client = MagicMock()
    mock_StockHistoricalDataClient.return_value = mock_client

    # Make sample close prices DataFrame
    dates = pd.date_range(start='2025-07-01', periods=5, freq='D')
    df = pd.DataFrame({"close": [100, 101, 102, 103, 104]}, index=dates)
    mock_bars = MagicMock()
    mock_bars.df = df
    mock_client.get_stock_bars.return_value = mock_bars

    result = get_recent_stock_prices(
        symbol="AAPL",
        start_date=datetime.date(2025, 7, 1),
        end_date=datetime.date(2025, 7, 5)
    )
    pd.testing.assert_series_equal(result, df["close"])
    assert isinstance(result.index, pd.DatetimeIndex)

test_valid_get_single_current_price()
test_valid_get_recent_stock_prices()