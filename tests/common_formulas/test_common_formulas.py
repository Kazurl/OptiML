import numpy as np
import pytest
import pandas as pd

from utils.common_formulas import annualized_volatility, price_sampling_adjustment
from utils.enums_market import SAMPLING_FREQ

# Helper to create sample price ranges
def create_sample_price_series():
    dates = pd.date_range(start='2024-01-01', periods=31, freq='D')
    prices = pd.Series(np.linspace(10, 12, 31), index=dates)  # 31 prices increasing linearly
    return prices

"""
Tests for price_sampling_adjustment
"""
# Test for DAILY price_sampling_adjustment 
def test_price_sampling_adjustment_daily():
    prices = create_sample_price_series()
    adjusted = price_sampling_adjustment(prices, SAMPLING_FREQ.DAILY.value)
    pd.testing.assert_series_equal(adjusted, prices)

# Test for WEEKLY price_sampling_adjustment 
def test_price_sampling_adjustment_weekly():
    prices = create_sample_price_series()
    adjusted = price_sampling_adjustment(prices, SAMPLING_FREQ.WEEKLY.value)
    
    expected_index = pd.date_range(start='2024-01-05', periods=5, freq='W-FRI')
    expected_prices = prices.resample('W-FRI').last()
    
    # Make sure expected index has freq attribute (already has from date_range)
    pd.testing.assert_series_equal(adjusted, expected_prices)

# Test for MONTHLY price_sampling_adjustment 
def test_price_sampling_adjustment_monthly():
    prices = create_sample_price_series()
    adjusted = price_sampling_adjustment(prices, SAMPLING_FREQ.MONTHLY.value)
    expected_index = pd.date_range(start='2024-01-31', periods=1, freq='ME')
    expected_prices = prices.resample('ME').last()
    pd.testing.assert_series_equal(adjusted, expected_prices)

# Test for invalid freq price_sampling_adjustment 
def test_price_sampling_adjustment_invalid():
    prices = create_sample_price_series()
    with pytest.raises(ValueError):
        price_sampling_adjustment(prices, 'invalid_freq')

# Test for price_sampling_adjustment with non date indexed prices
def test_price_sampling_adjustment_invalid_index():
    prices = pd.Series([10, 11, 12], index=[1, 2, 3])
    with pytest.raises(ValueError):
        price_sampling_adjustment(prices, SAMPLING_FREQ.DAILY.value)

"""
Tests for annualized_volatility
"""
# Test for valid annualized_volatility
def test_annualized_volatility_valid():
    prices = create_sample_price_series()
    for freq in [SAMPLING_FREQ.DAILY.value, SAMPLING_FREQ.WEEKLY.value]:
        adjusted_prices = price_sampling_adjustment(prices, freq)
        print(f"sampling freq: {freq}, adjustted_prices: {adjusted_prices}")
        vol = annualized_volatility(adjusted_prices, freq)
        print(vol)
        assert isinstance(vol, float)
        assert vol > 0

# Test for annualized_volatility with invalid sampling freq
def test_annualized_volatility_invalid_freq():
    prices = create_sample_price_series()
    with pytest.raises(ValueError):
        annualized_volatility(prices, 'invalid_freq')



if __name__ == "__main__":
    test_price_sampling_adjustment_daily()
    test_price_sampling_adjustment_weekly()
    test_price_sampling_adjustment_monthly()
    test_price_sampling_adjustment_invalid()
    test_price_sampling_adjustment_invalid_index()
    test_annualized_volatility_valid()
    test_annualized_volatility_invalid_freq()
    print("All tests passed!")
