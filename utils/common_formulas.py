from scipy.optimize import brentq
import numpy as np
import pandas as pd

from option_valuation.black_scholes_model import BlackScholesModel
from utils.enums_market import SAMPLING_FREQ
from utils.enums_option import OPTION_TYPE, PARAMETERS
from utils.options_formulas import call_blackscholes

"""
Adjust price series based on sampling frequency.
Frequency of data sampling: (daily, weekly, momnthly).
"""
def price_sampling_adjustment(
        prices: pd.Series,  # pandas series of daily closing prices
        sampling_freq: str
) -> pd.Series:
    if not isinstance(prices.index, pd.DatetimeIndex):
        raise ValueError("Price series must have a DateTimeIndex.")

    if sampling_freq == SAMPLING_FREQ.DAILY.value:
        return prices.dropna()
    elif sampling_freq == SAMPLING_FREQ.WEEKLY.value:
        # resample by week (last avail price in ea week)
        prices = prices.resample("W-FRI").last().dropna()
        return prices
    elif sampling_freq == SAMPLING_FREQ.MONTHLY.value:
        # resample by month (last avail price in ea mth)
        prices = prices.resample("ME").last().dropna()
        return prices
    else:
        raise ValueError(f"Unsupported sampling frequency: {sampling_freq}")


"""
Volatility (sigma) of single stock in stock market.
Formula: Sample standard deviation (an unbiased estimator of the log returns over specified period.
sigma = sqrt[(1/n-1) * sum((log(r) - E(r))^2)] * sqrt

Rolling window basis depending on:
1. Option window (default)
3. Frequency of data sampling: (daily, weekly, momnthly)
"""
def annualized_volatility(
    prices: pd.Series,  # pandas series of daily closing prices
    sampling_freq: str
):
    log_returns = np.log(prices/prices.shift(1)).dropna()
    daily_vol = log_returns.std(ddof=1)  # since sample estimate, ddof=1 i.e. division of N-1
    annualization_factor = {
        SAMPLING_FREQ.DAILY.value: 252,
        SAMPLING_FREQ.WEEKLY.value: 52,
        SAMPLING_FREQ.MONTHLY.value: 12
    }

    if sampling_freq not in annualization_factor:
        raise ValueError(f"Unsupported sampling frequency: {sampling_freq}")
    
    # Annualize volatility
    annual_vol = daily_vol * np.sqrt(annualization_factor[sampling_freq])
    return annual_vol


"""
Calculates implied volatility based on current option price for specific strike and expiry.
Use Black Scholes to backward induce volatility for that price alongside root-finder Brent's Method
with specified volatility band.

Core idea:
    - find volatility input into BS to find a BS price equal to observed market price
    - goal is to find the sigma that sets the (BS price - option price) = 0
      i.e root-finding within sigma range to find the implied volatility making BS price = option price
"""
def BS_brent_implied_volatility(
    option_price: float,
    S: float,
    X: float,
    T: int,  # days to expiry
    r: float,
    option_type: str
) -> float:
    # acceptable volatility range for this product
    sigma_lower = 1e-6
    sigma_upper = 5.0

    # payout | immediate exercise value
    intrinsic_value = max(0.0, (S-X) if option_type == OPTION_TYPE.CALL.value else (X-S))
    if option_price <= intrinsic_value + 1e-8:  # other tol: (1e-6, 1e-10) depending on numerical stability
        return 0.0
    
    def price_diff(sigma):
        params = {
            PARAMETERS.STOCK_PRICE.value: S,
            PARAMETERS.STRIKE_PRICE.value: X,
            PARAMETERS.DAYS_TO_EXPIRY.value: T,
            PARAMETERS.INTEREST_RATE.value: r,
            PARAMETERS.VOLATILITY.value: sigma
        }
        model = BlackScholesModel(option_type, params)
        BS_price = model.calculate_price()
        return BS_price - option_price

    # to attempt root-finding within reasonable sigma bandwidth
    try:
        return brentq(price_diff, sigma_lower, sigma_upper)
    except ValueError:  # value error likely means to change tolerance bandwidth of sigma
        return None
    

# todo: update to access data from actual API
"""
Calculates risk free rates for specified periods (in years).
Returns current risk-free rate (i.e. 3-month rate)

Currently:
function uses known set of rates for common maturities and find the closes match to requested period
"""
def get_risk_free_rate(
    period: float = None  # in years
) -> float:
    risk_free_rates = {
        0.25: 0.0415,  # 3 months
        0.5: 0.0420,   # 6 months
        1.0: 0.0430,   # 1 year
        2.0: 0.0450,   # 2 years
        5.0: 0.0480    # 5 years
    }
    
    if not period:
        # return current 3 month rate
        return risk_free_rates[0.25]

    # find closest maturity
    closest_mat = min(risk_free_rates.keys(), key=lambda x: abs(x-period))

    return risk_free_rates[closest_mat]