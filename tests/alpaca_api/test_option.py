import datetime
import pandas as pd
import pytest
from unittest.mock import patch, MagicMock
from alpaca.trading.enums import ContractType

from alpaca_api.options import parse_occ_symbol, get_specific_contract_IV


def test_parse_occ_symbol_call_put():
    call_symbol = "AAPL250829C00170000"
    parsed = parse_occ_symbol(call_symbol)
    assert parsed["underlying"] == "AAPL"
    assert parsed["type"] == "CALL"
    assert parsed["strike_price"] == 170.0
    assert parsed["expiration_date"] == datetime.date(2025, 8, 29)

    put_symbol = "AAPL250829P00170000"
    parsed = parse_occ_symbol(put_symbol)
    assert parsed["type"] == "PUT"


@patch("alpaca_api.options.OptionHistoricalDataClient")
def test_get_specific_contract_IV_direct_iv(mock_client_cls):
    mock_client = MagicMock()
    mock_client_cls.return_value = mock_client

    mock_snapshot = MagicMock()
    mock_snapshot.implied_volatility = 0.25

    mock_client.get_option_chain.return_value = {
        "AAPL250829C00170000": mock_snapshot
    }

    result = get_specific_contract_IV(
        symbol="AAPL",
        option_type="call option",
        X=170.0,
        expiry_start=datetime.date(2025, 8, 15),
        expiry_end=datetime.date(2025, 8, 29),
        expiry_window=30
    )
    assert result == 0.25


@patch("alpaca_api.options.get_single_current_price", return_value=100.0)
@patch("alpaca_api.options.BS_brent_implied_volatility", return_value=0.42)
@patch("alpaca_api.options.get_risk_free_rate", return_value=0.01)
@patch("alpaca_api.options.OptionHistoricalDataClient")
def test_get_specific_contract_IV_bsm_fallback(mock_client_cls, mock_rfr, mock_bs, mock_price):
    mock_client = MagicMock()
    mock_client_cls.return_value = mock_client

    mock_snapshot = MagicMock()
    mock_snapshot.implied_volatility = None
    # Simulate quote case
    mock_snapshot.latest_quote.ask_price = 105
    mock_snapshot.latest_quote.bid_price = 95

    mock_client.get_option_chain.return_value = {
        "AAPL250829C00170000": mock_snapshot
    }

    result = get_specific_contract_IV(
        symbol="AAPL",
        option_type="call option",
        X=170.0,
        expiry_start=datetime.date(2025, 8, 15),
        expiry_end=datetime.date(2025, 8, 29),
        expiry_window=30
    )
    assert result == 0.42


@patch("alpaca_api.options.annualized_volatility", return_value=0.30)
@patch("alpaca_api.options.price_sampling_adjustment")
@patch("alpaca_api.options.get_recent_stock_prices")
@patch("alpaca_api.options.OptionHistoricalDataClient")
def test_get_specific_contract_IV_hist_fallback(mock_client_cls, mock_prices, mock_adjust, mock_annvol):
    mock_client = MagicMock()
    mock_client_cls.return_value = mock_client

    # No option chain match
    mock_client.get_option_chain.return_value = {}

    # Fake price series
    dates = pd.date_range(start="2024-01-01", periods=5, freq='D')
    price_series = pd.Series([10, 11, 12, 13, 14], index=dates)
    mock_prices.return_value = price_series
    mock_adjust.return_value = price_series

    result = get_specific_contract_IV(
        symbol="AAPL",
        option_type="call option",
        X=170.0,
        expiry_start=datetime.date(2024, 1, 15),
        expiry_end=datetime.date(2024, 2, 15),
        expiry_window=30
    )
    assert result == 0.30


@patch("alpaca_api.options.OptionHistoricalDataClient", side_effect=Exception("API failure"))
def test_get_specific_contract_IV_exception(mock_client_cls):
    with pytest.raises(Exception) as excinfo:
        get_specific_contract_IV(
            symbol="AAPL",
            option_type="call option",
            X=170.0,
            expiry_start=datetime.date(2024, 1, 15),
            expiry_end=datetime.date(2024, 2, 15),
            expiry_window=30
        )
    assert "Error fetching data for ticker" in str(excinfo.value)


# Call all tests
test_parse_occ_symbol_call_put()
test_get_specific_contract_IV_direct_iv()
test_get_specific_contract_IV_bsm_fallback()
test_get_specific_contract_IV_hist_fallback()
test_get_specific_contract_IV_exception()