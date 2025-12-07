import numpy as np
import pytest
import pandas as pd

from utils.common_formulas import (
    annualized_volatility,
    BS_brent_implied_vol,
    BS_NR_implied_vol,
    implied_vol,
    price_sampling_adjustment,
)
from utils.enums_market import SAMPLING_FREQ
from utils.enums_option import OPTION_CONSTANTS, OPTION_TYPE
from utils.options_formulas import bs_price


""" todo: delete when done
export PYTHONPATH=$(pwd)
python tests/common_formulas/test_common_formulas.py
"""

TOL = 1e-2  # Tolerance for volatility accuracy

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



"""
Tests for BS_brent_implied_vol
"""
def test_bs_brent_implied_vol_atm_call():
    S, K, T_years, r, true_iv = 100, 100, 30/365, 0.02, 0.25
    T_days = int(T_years * 365)
    price = bs_price(S, K, T_years, r, true_iv, "call")
    brent_iv = BS_brent_implied_vol(price, S, K, T_days, r, OPTION_TYPE.CALL.value)
    assert brent_iv is not None
    assert np.isclose(brent_iv, true_iv, atol=TOL)

def test_bs_brent_implied_vol_otm_put():
    S, K, T_years, r, true_iv = 95, 100, 45/365, 0.01, 0.35
    T_days = int(T_years * 365)
    price = bs_price(S, K, T_years, r, true_iv, "put")
    brent_iv = BS_brent_implied_vol(price, S, K, T_days, r, OPTION_TYPE.PUT.value)
    assert brent_iv is not None
    assert np.isclose(brent_iv, true_iv, atol=TOL)

def test_bs_brent_implied_vol_zero_price():
    S, K, T_years, r = 70, 100, 40/365, 0.01
    T_days = int(T_years * 365)
    price = 0.0
    iv = BS_brent_implied_vol(price, S, K, T_days, r, OPTION_TYPE.CALL.value)
    assert iv == OPTION_CONSTANTS.SIGMA_LOWER.value

def test_bs_brent_implied_vol_intrinsic_price():
    S, K, T_years, r = 120, 100, 2/365, 0.02
    T_days = int(T_years * 365)
    price = max(S-K, 0)
    iv = BS_brent_implied_vol(price, S, K, T_days, r, OPTION_TYPE.CALL.value)
    assert iv == OPTION_CONSTANTS.SIGMA_LOWER.value



"""
Tests for BS_NR_implied_vol
"""
def test_bs_nr_implied_vol_atm_call():
    S, K, T_years, r, true_iv = 100, 100, 60/365, 0.02, 0.22
    price = bs_price(S, K, T_years, r, true_iv, "call")
    nr_iv, bad_exit = BS_NR_implied_vol(price, S, K, T_years, r, "call")
    assert not bad_exit
    assert np.isclose(nr_iv, true_iv, atol=TOL)

def test_bs_nr_implied_vol_itm_put():
    S, K, T_years, r, true_iv = 85, 100, 90/365, 0.03, 0.28
    price = bs_price(S, K, T_years, r, true_iv, "put")
    nr_iv, bad_exit = BS_NR_implied_vol(price, S, K, T_years, r, "put")
    assert not bad_exit
    assert np.isclose(nr_iv, true_iv, atol=TOL)

def test_bs_nr_implied_vol_zero_price():
    S, K, T_years, r = 70, 100, 30/365, 0.01
    price = 0.0
    nr_iv, bad_exit = BS_NR_implied_vol(price, S, K, T_years, r, "call")
    assert bad_exit
    assert nr_iv <= 0.01  # Should be very close to zero

def test_bs_nr_implied_vol_high_price_max_iv():
    S, K, T_years, r = 100, 100, 15/365, 0.01
    price = 15
    nr_iv, bad_exit = BS_NR_implied_vol(price, S, K, T_years, r, "call")
    assert nr_iv <= 5.0



"""
Tests for implied_vol
"""
def test_implied_vol_atm_call():
    S, K, T, r, true_iv = 100, 100, 30/365, 0.03, 0.2
    price = bs_price(S, K, T, r, true_iv, "call")
    out_iv = implied_vol(price, S, K, T, r, OPTION_TYPE.CALL.value)

    assert np.isclose(out_iv, true_iv, atol=TOL)

def test_implied_vol_otm_put():
    S, K, T, r, true_iv = 90, 100, 60/365, 0.01, 0.4
    price = bs_price(S, K, T, r, true_iv, "put")
    out_iv = implied_vol(price, S, K, T, r, OPTION_TYPE.PUT.value)
    assert np.isclose(out_iv, true_iv, atol=TOL)

def test_implied_vol_deep_itm_call():
    S, K, T, r, true_iv = 140, 100, 120/365, 0.01, 0.15
    price = bs_price(S, K, T, r, true_iv, "call")
    out_iv = implied_vol(price, S, K, T, r, OPTION_TYPE.CALL.value)
    assert np.isclose(out_iv, true_iv, atol=TOL)

def test_implied_vol_zero_price_returns_zero_iv():
    S, K, T, r = 80, 100, 20/365, 0.01
    price = 0.0
    out_iv = implied_vol(price, S, K, T, r, OPTION_TYPE.CALL.value)
    assert out_iv < 1e-3

def test_implied_vol_intrinsic_returns_zero_iv():
    S, K, T, r = 115, 100, 1/365, 0.01
    price = S - K
    out_iv = implied_vol(price, S, K, T, r, OPTION_TYPE.CALL.value)
    assert out_iv < 1e-3

def test_implied_vol_nr_fallback_to_brent():
    # Construct a scenario that should fail NR (e.g., far ITM/OTM, low vega, T ~0)
    # or monkeypatch BS_NR_implied_vol to always return bad_exit for testing
    S, K, T, r = 100, 100, 30/365, 0.02
    price = bs_price(S, K, T, r, 0.5, "call")
    # Patch NR path: manually force bad_exit, Brent must be invoked and succeed
    original_bs_nr = BS_NR_implied_vol
    def always_fail_nr(*args, **kwargs):
        return (0.5, True)
    import utils.common_formulas as cf
    cf.BS_NR_implied_vol = always_fail_nr  # Monkeypatch for this test
    try:
        iv = implied_vol(price, S, K, T, r, OPTION_TYPE.CALL.value)
        assert iv is not None, "Implied vol root-finder failed to converge."
        assert np.isclose(iv, 0.5, atol=1e-2) # Brent must recover correct IV
    finally:
        cf.BS_NR_implied_vol = original_bs_nr  # Unpatch

def test_implied_vol_high_market_price_max_band():
    S, K, T, r = 100, 100, 15/365, 0.01
    price = 50  # unrealistically high price
    out_iv = implied_vol(price, S, K, T, r, OPTION_TYPE.CALL.value)
    assert out_iv <= 5.0



if __name__ == "__main__":
    """
    Tests for price_sampling_adjustment
    """
    test_price_sampling_adjustment_daily()
    test_price_sampling_adjustment_weekly()
    test_price_sampling_adjustment_monthly()
    test_price_sampling_adjustment_invalid()
    test_price_sampling_adjustment_invalid_index()
    """
    Tests for annualized_volatility
    """
    test_annualized_volatility_valid()
    test_annualized_volatility_invalid_freq()
    """
    Tests for BS_brent_implied_vol
    """
    test_bs_brent_implied_vol_atm_call()
    test_bs_brent_implied_vol_otm_put()
    test_bs_brent_implied_vol_zero_price()
    test_bs_brent_implied_vol_intrinsic_price()
    """
    Tests for BS_NR_implied_vol
    """
    test_bs_nr_implied_vol_atm_call()
    test_bs_nr_implied_vol_itm_put()
    test_bs_nr_implied_vol_zero_price()
    test_bs_nr_implied_vol_high_price_max_iv()
    """
    Tests for implied_vol
    """
    test_implied_vol_atm_call()
    test_implied_vol_otm_put()
    test_implied_vol_deep_itm_call()
    test_implied_vol_zero_price_returns_zero_iv()
    test_implied_vol_intrinsic_returns_zero_iv()
    test_implied_vol_nr_fallback_to_brent()
    test_implied_vol_high_market_price_max_band()
    print("All tests passed!")
