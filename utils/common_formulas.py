import logging
import os

import certifi
import httpx
import inspect
import numpy as np
import pandas as pd
import requests
import time
import yfinance as yf
from bs4 import BeautifulSoup
from datetime import datetime, timedelta, timezone
from fredapi import Fred
from scipy.optimize import brentq
from scipy.stats import norm
from scipy.stats.mstats import winsorize

from binance_api.utils import (
    get_realized_vol,
    _binance_symbol_for_base,
    _fetch_binance_ohlc,
)
from option_valuation.black_scholes_model import BlackScholesModel
from utils.enums_market import SAMPLING_FREQ
from utils.enums_option import OPTION_CONSTANTS, OPTION_TYPE, PARAMETERS
from utils.options_formulas import bs_price



# === Statistics ===
def _zscore_list(
        vals: list[float]
    ) -> list[float]:
    """
    Returns z-scores of the input list.
    If len(vals)<3 or stddev is too small, returns zeros.

    Parameters:
        vals (list[float]): list of values

    Returns:
        list[float]: list of z-scores
    """
    if not vals or len(vals) < 3:
        return [0.0 for _ in vals]
    m = float(np.mean(vals)); s = float(np.std(vals, ddof=1))
    if s <= 1e-12:
        return [0.0 for _ in vals]
    return [(v - m)/s for v in vals]


def price_sampling_adjustment(
        prices: pd.Series,  # pandas series of daily closing prices
        sampling_freq: str
) -> pd.Series:
    """
    Adjust price series based on sampling frequency.
    Frequency of data sampling: (daily, weekly, momnthly).

    Parameters:
        prices (pd.Series): pandas series of daily closing prices
        sampling_freq (str): frequency of data sampling (daily, weekly, monthly)

    Returns:
        pd.Series:  pandas series with adjusted sampling frequency

    Raises:
        ValueError:
            if prices.index is not a DateTimeIndex
            if sampling_freq is not one of the supported frequencies
    """
    
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



# === Implied Volatility (IV) ===
def annualized_volatility(
    prices: pd.Series,  # pandas series of daily closing prices
    sampling_freq: str
):
    """
    Annualized volatility (sigma) of a single stock in the stock market.
    Formula: Sample standard deviation (an unbiased estimator of the log returns over specified period).
    sigma = sqrt[(1/n-1) * sum((log(r) - E(r))^2)] * sqrt

    Rolling window basis depending on:
    1. Option window (default)
    3. Frequency of data sampling: (daily, weekly, monthly)

    Parameters:
        prices (pd.Series): pandas series of daily closing prices
        sampling_freq (str): frequency of data sampling (daily, weekly, monthly)

    Returns:
        float: annualized volatility
    """

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


def BS_brent_implied_vol(
    option_price: float,
    S: float,
    K: float,
    T: int,  # days to expiry
    r: float,
    option_type: str = OPTION_TYPE.CALL.value
) -> float:
    """
    Calculates implied volatility based on current option price for specific strike and expiry.
    Use Black Scholes to backward-induce volatility for that price alongside root-finder
    Brent's Method with specified volatility band.

    Core idea:
        - find volatility input into BS to find a BS price equal to observed market price
        - goal is to find the sigma that sets the (BS price - option price) = 0
          i.e root-finding within sigma range to find the implied volatility making BS price = option price

    Parameters:
        option_price (float): current option price for specific strike and expiry
        S (float): current underlying price
        K (float): strike price
        T (int): days to expiry
        r (float): risk-free rate (annualized, decimal)
        option_type (str): either 'call' or 'put'

    Returns:
        float: implied volatility

    Note:
        - if time to expiry is nearly zero, almost all non-intrinsic time value vanishes.
    """

    # acceptable volatility range for this product
    sigma_lower = OPTION_CONSTANTS.SIGMA_LOWER.value
    sigma_upper = OPTION_CONSTANTS.SIGMA_UPPER.value

    # payout | immediate exercise value
    intrinsic_value = max(0.0, (S-K) if option_type.lower() in OPTION_TYPE.CALL.value else (K-S))
    if option_price <= intrinsic_value + 1e-8:  # other tol: (OPTION_CONSTANTS.SIGMA_LOWER.value's 1e-6, 1e-10) depending on numerical stability
        return OPTION_CONSTANTS.SIGMA_LOWER.value
    
    def price_diff(sigma):
        # Compute difference between BS price and option price for given volatility
        params = {
            PARAMETERS.STOCK_PRICE.value: S,
            PARAMETERS.STRIKE_PRICE.value: K,
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
    except ValueError as e:  # value error likely means to change tolerance bandwidth of sigma
        logging.warning(f"Brent implied vol failed for price={option_price}, S={S}, K={K}, T={T}, r={r}, error={e}")
        return OPTION_CONSTANTS.SIGMA_LOWER.value  # return small +ve volatility to avoid errors in BSM

    

def BS_NR_implied_vol(
        target_price: float,
        S: float,
        K: float,
        T: float,
        r: float,
        option_type: str = "call"
    ) -> tuple[float, bool]:  # todo: document on gdoc
    """
    Calculates Implied volatility using Newton-Raphson method.
    Newton-Raphson method:
    sigma_new = sigma_old - [BS_price(sigma_old) - target_price] / vega(sigma_old)
        1. Iterative root-finding using local derivative ("slope") information.
        2. Start with initial guess of sigma.
        3. Calculate price at current sigma.
        4. Calculate derivative of price at current sigma.
        5. Calculate difference between target price and current price.
        6. Update sigma by subtracting difference divided by derivative.
        7. Repeat steps 3-6 until difference is less than tolerance.
    Returns sigma as float.

    Parameters:
        target_price (float): target price
        S (float): current underlying price
        K (float): strike price
        T (float): time to expiry in years
        r (float): risk-free rate (annualized, decimal)
        option_type (str): either 'call' or 'put'

    Returns:
        float: implied volatility
        bool: flag set for early/ bad exit conditions
    """
    
    if target_price <= 0:  # early exit for invalid prices
        return OPTION_CONSTANTS.SIGMA_LOWER.value, True  # if target price non +ve, return small +ve volatility to avoid errors in BSM
    sigma = 0.5  # start with 50% annualized vol
    for _ in range(60):
        price = bs_price(S, K, T, r, sigma, option_type)
        d1 = (np.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * np.sqrt(T))
        vega = S * norm.pdf(d1) * np.sqrt(T)
        diff = price - target_price
        if abs(diff) < OPTION_CONSTANTS.SIGMA_LOWER.value:  # found IV within tol
            return float(sigma), False
        if vega < 1e-8:  # early exit if vega too small
            break
        sigma -= diff / vega
        sigma = max(min(sigma, 5.0), OPTION_CONSTANTS.SIGMA_LOWER.value)
    return float(sigma), False


def implied_vol(
        option_price: float,
        S: float,
        K: float,
        T: float,
        r: float,
        option_type: str = "call"
    ) -> float: 
    """
    Compute implied volatility from option price using two sources of root-finders:
    1. Newton-Raphson (NR) method for root-finding
    2. Brent's Method for root-finding

    Parameters:
        option_price (float): current option price for specific strike and expiry
        S (float): current underlying price
        K (float): strike price
        T (float): time to expiry in years
        r (float): risk-free rate (annualized, decimal)
        option_type (str): either 'call' or 'put'

    Returns:
        float: implied volatility
    """

    sources = (BS_NR_implied_vol, BS_brent_implied_vol)
    for fn in sources:
        if fn is BS_NR_implied_vol:
            iv, bad_exit = fn(option_price, S, K, T, r, option_type)
            if bad_exit:
                continue
            else:
                return iv
        else:
            iv = fn(option_price, S, K, int(T * 365), r, option_type)
            return iv
        
    return OPTION_CONSTANTS.SIGMA_LOWER.value  # if all fail



# === Realized Volatility ===
def _realized_vol_yang_zhang_from_ohlc(  # todo: tetatively removed, replaced with other
        O: list[float],
        H: list[float],
        L: list[float],
        C: list[float],
        trading_days: int = 365
    ) -> float | None:
    """
    Compute Yang-Zhang realized volatility from OHLC data (adaptive by DTE).

    Parameters:
        O (list[float]): Open prices
        H (list[float]): High prices
        L (list[float]): Low prices
        C (list[float]): Close prices
        trading_days (int): Number of trading days to annualize the realized volatility
                            (365 trading days per year)

    Returns:
        float: Calculated value of the realized volatility
        or None if less than 2 days of data are available.
    """

    n = len(C)
    if n < 2: 
        return None
    # build series for t=1..n-1
    oc = np.log(np.array(O[1:], float) / np.array(C[:-1], float))
    co = np.log(np.array(C[1:], float) / np.array(O[1:], float))
    u  = np.log(np.array(H[1:], float) / np.array(O[1:], float))
    d  = np.log(np.array(L[1:], float) / np.array(O[1:], float))

    oc, co, u, d = (winsorize(oc, limits=[0.01, 0.01]),
                    winsorize(co, limits=[0.01, 0.01]),
                    winsorize(u, limits=[0.01, 0.01]),
                    winsorize(d, limits=[0.01, 0.01]))

    m = len(co)
    if m < 3:
        return None
    var_oc = float(np.var(oc, ddof=1))
    var_co = float(np.var(co, ddof=1))
    rs = float(np.mean(u * (u - co) + d * (d - co)))
    k = 0.34 / (1.34 + (m + 1) / (m - 1)) if m > 1 else 0.34
    var_yz = var_oc + k * var_co + (1.0 - k) * rs  # daily variance
    # returned annualized sigma i.e. stddev
    return np.sqrt(max(0.0, var_yz)) * np.sqrt(trading_days)


# def get_realized_vol_yz_dynamic(
#         base: str,
#         dte_days: float
#     ) -> float:
#     """
#     Compute realized volatility using Yang-Zhang method from OHLC data (adaptive by DTE).
#     If less than 2 days of data available, fallback to binance's realized vol.

#     Parameters:
#         base (str): Base currency (e.g. BTCUSDT)
#         dte_days (float): Days to expiration (DTE) which determines the lookback window

#     Returns:
#         float: Calculated value of the realized volatility
#         or None if less than 2 days of data are available.
#     """

#     if dte_days <= 7:
#         lb = 14
#     elif dte_days <= 30:
#         lb = 30
#     else:
#         lb = 45
#     try:
#         symbol = _binance_symbol_for_base(base)
#         O, H, L, C = _fetch_binance_ohlc(symbol, lb)
#         yz = _realized_vol_yang_zhang_from_ohlc(O, H, L, C, trading_days=365)
#         if yz and 0.0001 <= yz <= 5.0:
#             return float(yz)
#     except Exception as e:
#         logging.warning(f"get_realized_vol_yz_dynamic failed: {e}")
#         pass
#     # fallback: your original CC/EWMA on BTC (kept for resilience)
#     return float(await get_realized_vol(days=30))

async def get_realized_vol_yz_dynamic(
        base: str,
        dte_days: float
    ) -> float:
    """
    Compute realized volatility using Yang-Zhang method from OHLC data (adaptive by DTE).
    If less than 2 days of data available, fallback to binance's realized vol.

    Parameters:
        base (str): Base currency (e.g. BTCUSDT)
        dte_days (float): Days to expiration (DTE) which determines the lookback window

    Returns:
        float: Calculated value of the realized volatility
        or None if less than 2 days of data are available.
    """

    if dte_days <= 7:
        lb = 14
    elif dte_days <= 30:
        lb = 30
    else:
        lb = 45
    try:
        symbol = _binance_symbol_for_base(base)
        O, H, L, C = await _fetch_binance_ohlc(symbol, lb)
        yz = _realized_vol_yang_zhang_from_ohlc(O, H, L, C, trading_days=365)
        if yz and 0.0001 <= yz <= 5.0:
            return float(yz)
    except Exception as e:
        logging.warning(f"get_realized_vol_yz_dynamic failed: {e}")
        pass
    # fallback: your original CC/EWMA on BTC (kept for resilience)
    return float(await get_realized_vol(days=30))


async def _daily_yz_series(
        base: str,
        lookback_days: int = 120
    ) -> np.ndarray:
    """
    Compute a series of daily Yang-Zhang realized volatility from OHLC data.

    Parameters:
        base (str): Base currency (e.g. BTC, ETH)
        lookback_days (int): Lookback window in days for the Yang-Zhang realized volatility

    Returns:
        np.ndarray: A numpy array of daily Yang-Zhang realized volatility values
    """
    symbol = _binance_symbol_for_base(base)
    O, H, L, C = await _fetch_binance_ohlc(symbol, lookback_days + 2)
    if len(C) < 3:
        return np.array([])
    O = np.array(O, float); H = np.array(H, float); L = np.array(L, float); C = np.array(C, float)
    oc = np.log(O[1:] / C[:-1])
    co = np.log(C[1:] / O[1:])
    u  = np.log(H[1:] / O[1:])
    d  = np.log(L[1:] / O[1:])

    # winsorize 1% tails
    oc, co, u, d = (winsorize(oc, limits=[0.01, 0.01]),
                    winsorize(co, limits=[0.01, 0.01]),
                    winsorize(u, limits=[0.01, 0.01]),
                    winsorize(d, limits=[0.01, 0.01]))

    m = len(co)
    k = 0.34 / (1.34 + (m + 1) / (m - 1)) if m > 1 else 0.34
    RS = u*(u - co) + d*(d - co)
    yz_var = oc*oc + k*(co*co) + (1.0 - k)*RS
    yz_var = np.clip(yz_var, 0.0, None)
    return np.sqrt(yz_var)  # daily sigma_t


async def _har_forecast_annualized(
        base: str,
        min_hist: int = 60
    ) -> float | None:  # todo: document on gdoc
    """
    RV forecast with HAR method using daily YZ series.
    (Vol today depends on yesterday, past week, past month)
    Requires at least min_hist days of history.
    ln(RV) = beta_0 + beta_1*ln(d) + beta_2*ln(w) + beta_3*ln(m)
    where,
        d = previous day realized vol
        w = mean realized vol over last week (5 days)
        m = mean realized vol over last month (22 days)

    Parameters:
        base (str): Base currency (e.g. BTC, ETH)
        min_hist (int): Minimum history in days

    Returns:
        float: Forecasted value of the realized volatility
    """
    
    rv_d = await _daily_yz_series(base, lookback_days=max(120, min_hist+30))
    if rv_d.size < min_hist:
        return None
    # build features for t>=22 (need monthly window)
    y = []
    X = []
    for t in range(22, rv_d.size):
        d = rv_d[t-1]
        w = rv_d[max(0, t-5):t].mean()
        m = rv_d[max(0, t-22):t].mean()
        if d<=0 or w<=0 or m<=0:
            continue
        X.append([1.0, np.log(d), np.log(w), np.log(m)])
        y.append(np.log(rv_d[t]))
    if len(y) < 20:
        return None
    X = np.asarray(X); y = np.asarray(y)
    try:
        beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    except Exception:
        return None
    # one-step-ahead forecast
    d = rv_d[-1]
    w = rv_d[-5:].mean() if rv_d.size >= 5 else d
    m = rv_d[-22:].mean() if rv_d.size >= 22 else w
    # ln(RV) = beta_0 + beta_1*ln(d) + beta_2*ln(w) + beta_3*ln(m)
    ln_next = float(beta[0] + beta[1]*np.log(max(d,1e-9)) + beta[2]*np.log(max(w,1e-9)) + beta[3]*np.log(max(m,1e-9)))
    daily_sigma = max(1e-8, np.exp(ln_next))  # exp to get sigma since ln_next is now log(sigma)
    return daily_sigma * np.sqrt(365.0)  # annualized


async def _garch11_forecast_annualized(
        base: str,
        lookback_days: int = 365
    ) -> float | None:  # todo: document on gdoc
    """
    RV forecast with GARCH(1,1) forecast using close-to-close log returns.
    GARCH(1,1) is a classic time-series model for conditional volatility.

    Parameters:
        base (str): Base currency (e.g. BTC, ETH)
        lookback_days (int): Lookback window in days

    Returns:
        float: Forecasted next day value of the realized volatility
        or None if not enough data.
    """

    symbol = _binance_symbol_for_base(base)
    try:
        _O, _H, _L, C = await _fetch_binance_ohlc(symbol, lookback_days + 2)
    except Exception:
        return None
    
    if len(C) < 30:
        return None
    r = np.diff(np.log(np.array(C, float)))
    # winsorize 1% tails
    lo, hi = np.quantile(r, 0.01), np.quantile(r, 0.99)
    r = np.clip(r, lo, hi)
    v_bar = float(np.var(r, ddof=1))
    alpha, beta = 0.05, 0.90
    omega = v_bar * (1.0 - alpha - beta)
    if omega <= 0:
        omega = 1e-8
    sigma2 = v_bar
    for ri in r:  # Runs through returns in order, recursively updating variance sigma2
        sigma2 = omega + alpha * (ri**2) + beta * sigma2
    # next-day variance
    sigma2_f = omega + alpha * (r[-1]**2) + beta * sigma2
    daily_sigma = np.sqrt(max(1e-12, sigma2_f))
    return daily_sigma * np.sqrt(365.0)


async def _forecast_rv_annualized(
        base: str,
        model: str = "har"
    ) -> float | None:
    """
    Forecast next-day annualized realized vol using specified model.
    model: "har" (default) or "garch"
    Returns annualized sigma or None if not enough data.

    Parameters:
        base (str): Base currency (e.g. BTC, ETH)
        model (str): Forecast model ("har" or "garch")

    Returns:
        float: Forecasted next day value of the realized volatility
    """

    model = (model or "har").lower()
    if model == "garch":
        f = await _garch11_forecast_annualized(base)
        if f is not None:
            return f
        # fall back to HAR
    return await _har_forecast_annualized(base)



# === Risk-free rates ===
async def getNominalRates_ustreasurycurve(
    date_start: datetime = None,
    date_end: datetime = None,
    express: bool = True,
    verify_req: bool = True,
    retries: int = 2,
    backoff: float = 0.7
) -> pd.DataFrame:
    """
    Fetches the daily treasury yield curve data from the US Treasury website.

    Parameters:
        date_start (datetime, optional): The start date of the period. Defaults to one year ago.
        date_end (datetime, optional): The end date of the period. Defaults to the current date.
        verify_req (bool, optional): Whether to verify the SSL certificate of the website. Defaults to True.
        retries (int, optional): The number of times to retry the request if it fails. Defaults to 2.
        backoff (float, optional): The backoff time in seconds. Defaults to 0.7.

    Returns:
        pd.DataFrame: A pandas DataFrame containing the treasury yield curve data for the specified period.
    """
    
    if not date_start or (not isinstance(date_start, datetime) and not isinstance(date_start, str)):
        date_start = datetime.now() - timedelta(days=365)
    if not date_end or (not isinstance(date_end, datetime) and not isinstance(date_end, str)):
        date_end = datetime.now()

    # Drop tzinfo from dates before conversion
    date_start = date_start.replace(tzinfo=None) if date_start.tzinfo is not None else date_start
    date_end = date_end.replace(tzinfo=None) if date_end.tzinfo is not None else date_end

    years_list = list(range(int(date_start.strftime("%Y")), int(date_end.strftime("%Y"))+1))
    tbondvals = []
    for y in years_list:
        for i in range(max(1, retries)):
            try:
                async with httpx.AsyncClient(verify=certifi.where()) as client:
                    res = await client.get(
                        'https://home.treasury.gov/resource-center/data-chart-center/interest-rates/pages/xml?data=daily_treasury_yield_curve&field_tdr_date_value=' + str(y)
                    )
                    res.raise_for_status()
                    soup = BeautifulSoup(res.text,features="xml")
                    table = soup.find_all("m:properties")
                    for row in table:
                        try:
                            try:
                                thrmth = row.find("d:BC_3MONTH").text
                            except:
                                thrmth = np.nan
                            if express:
                                tbondvals.append([
                                    row.find("d:NEW_DATE").text[:10],
                                    thrmth
                                ])
                                continue
                            try:
                                onemth = row.find("d:BC_1MONTH").text
                            except:
                                onemth = np.nan
                            try:
                                twomth = row.find("d:BC_2MONTH").text
                            except:
                                twomth = np.nan
                            try:
                                twentyyr = row.find("d:BC_20YEAR").text
                            except:
                                twentyyr = np.nan
                            try:
                                thirtyyr = row.find("d:BC_30YEAR").text
                            except:
                                thirtyyr = np.nan
                            tbondvals.append([
                                row.find("d:NEW_DATE").text[:10],
                                onemth,
                                twomth,
                                thrmth,
                                row.find("d:BC_6MONTH").text,
                                row.find("d:BC_1YEAR").text,
                                row.find("d:BC_2YEAR").text,
                                row.find("d:BC_3YEAR").text,
                                row.find("d:BC_5YEAR").text,
                                row.find("d:BC_10YEAR").text,
                                twentyyr,
                                thirtyyr
                            ])
                        except:
                            pass
            except Exception as e:
                logging.info(f"RFR Treasury attempt {i} failed: {e}")
            time.sleep(backoff)
            backoff *= 2
    
    # Setting up dataframe
    cols = ["Date", "1M", "2M", "3M", "6M", "1Y", "2Y", "3Y", "5Y", "10Y", "20Y", "30Y"] if not express else ["Date", "3M"]
    df = pd.DataFrame(tbondvals, columns=cols)
    df.iloc[:, 1:] = df.iloc[:, 1:].apply(pd.to_numeric)
    df["Date"] = pd.to_datetime(df["Date"])
    df.sort_values("Date", inplace=True)
    df = df.loc[(df["Date"] >= pd.to_datetime(date_start)) & (df["Date"] <= pd.to_datetime(date_end))].copy()
    df.reset_index(drop=True, inplace=True)
    
    return df


def _fred_dgs3mo_api(
        max_age_days: int = 30
    ) -> float | None:
    """
    Fetches the 3-Month Treasury Constant Maturity Rate (Annualized) from FRED and returns the latest value as a float.

    Parameters:
        max_age_days (int): Max age of the data point in days. If the data point is older 
                            than this, None is returned.

    Returns:
        float: The latest value of the 3-Month Treasury Constant Maturity Rate 
               (Annualized)
        or None if no data point or all too old.
    """
    try:
        fred = Fred(api_key=os.getenv("FRED_API_KEY"))
        today = datetime.now(timezone.utc)
        data = fred.get_series("DGS3MO")
        for id, val in data.iloc[::-1].items():
            id = id.replace(tzinfo=timezone.utc) if id.tzinfo is None else id
            if (today - id).days > max_age_days:
                continue
            val = float(val) / 100.0
            if 0.0 <= val <= 0.15:
                logging.info(f"RFR FRED DGS3MO {id} -> {val*100:.2f}%")
                return val

    except Exception as e:
        print(e)

    logging.debug("_fred_dgs3mo_api empty result set")
    return None


async def _treasury_yield_curve_api(
        max_age_days: int = 30
    ) -> float | None:
    """
    Fetches the 3 Month treasury yield curve data from the US Treasury website and returns the latest value as a float.

    Parameters:
        max_age_days (int): Max age of the data point in days. If the data point is older 
                            than this, None is returned.

    Returns:
        float: The latest value of the 3-Month Treasury Constant Maturity Rate 
               (Annualized)
        or None if no data point or all too old.
    """

    try:
        df = await getNominalRates_ustreasurycurve(
            date_start=(datetime.now(timezone.utc)-timedelta(days=365)),
            date_end=datetime.now(timezone.utc)
        )
        data = df["3M"]
        data.index = df["Date"]
        today = datetime.now(timezone.utc)
        for dt, val in data.iloc[::-1].items():
            dt = dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt
            if (today - dt).days > max_age_days:
                continue
            val = float(val) / 100.0
            if 0.0 <= val <= 0.15:
                logging.info(f"RFR Treasury CSV {dt.isoformat()} -> {val*100:.2f}%")
                return val
    except Exception as e:
        logging.error(f"Error in _treasury_yield_curve_api: {e}")

    logging.debug(f"_treasury_yield_curve_api empty result set")
    return None


def _yahoo_irx_rate_api(max_age_days: int = 30) -> float | None:
    """
    Fetches the 3 Month Treasury Constant Maturity Rate (Annualized) from Yahoo Finance and returns the latest value as a float.

    Parameters:
        max_age_days (int): Max age of the data point in days. If the data point is older 
                            than this, None is returned.

    Returns:
        float: The latest value of the 3-Month Treasury Constant Maturity Rate 
               (Annualized)
        or None if no data point or all too old.
    """

    data = yf.download(
        tickers="^IRX",
        period="3mo",
        interval="1d",
        progress=False
    )
    today = datetime.now(timezone.utc)
    if data.empty or "Close" not in data:
        logging.debug(f"yahoo_irx_rate_api empty result set")
        return None
    # Get the most recent valid row within age limit
    for dt, row in reversed(list(data.iterrows())):
        val = row["Close"]
        if val.empty:
            continue
        val = val["^IRX"]
        dt = dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt
        if (today - dt).days <= max_age_days and 0.0 <= val / 100.0 <= 0.15:
            logging.info(f"RFR Yahoo IRX {dt.isoformat()} -> {val:.2f}%")
            return val / 100.0
        
    logging.debug(f"yahoo_irx_rate_api empty result set")
    return None


async def get_risk_free_rate(
        cache: dict,
        ttl_seconds: int = 3 * 60 * 60  # 3 hours
) -> float:
    """
    Fetches the Risk Free Rate (RFR) from FRED/Treasury/Yahoo and returns the latest value.

    Parameters:
        ttl_seconds (int): Max age of the data point in seconds. If the data point is older 
                            than this, None is returned.
    
    Returns:
        float: The latest value of the Risk Free Rate (RFR), or arbitrary 0.05 if every source fails.
    """

    now = time.time()
    if cache["val"] is not None and (now - cache["t"] <= ttl_seconds):
        return cache["val"]
    try:
        override = os.getenv("RFR_OVERRIDE")  # todo: what is this override for? when is it activated and how is the value determined?
        if override is not None:
            val = float(override)
            if 0.0 <= val <= 0.15:
                logging.warning(f"RFR override used: {val*100:.2f}%")
                cache.update({"t": now, "val": val})
                return val
    except Exception:
        pass

    sources = (_fred_dgs3mo_api, _treasury_yield_curve_api, _yahoo_irx_rate_api,)
    for fn in sources:
        try:
            if inspect.iscoroutinefunction(fn):
                val = await fn()
            else:
                val = fn()
        except Exception as e:
            logging.info(f"RFR source {fn.__name__} failed: {e}")
            val = None
        if val is not None:
            val = float(max(0.0, min(val, 0.15)))
            cache.update({"t": now, "val": val})
            return val
        
    logging.warning("RFR: all sources failed; hard fallback 5.00%")
    cache.update({"t": now, "val": 0.05})
    return 0.05


