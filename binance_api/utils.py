import logging

import asyncio
import certifi
import httpx
import numpy as np
import requests


def _binance_symbol_for_base(
        base: str
    ) -> str:
    """
    Returns the Binance symbol for the given base.

    Parameters:
        base (str): The base currency of the index. E.g. "BTC", "ETH"

    Returns:
        str: The Binance symbol for the given base, or None if the request fails.
    """
    
    base = base.upper()
    if base == "BTC": return "BTCUSDT"
    if base == "ETH": return "ETHUSDT"
    return f"{base}USDT"

# def _fetch_binance_ohlc(
#         symbol: str,
#         days: int
#     ) -> tuple[list[float], list[float], list[float], list[float]] | None:
#     """
#     Fetches the Binance OHLC data for the given symbol and number of days.

#     Parameters:
#         days (int): The number of days to fetch.

#     Returns:
#         tuple[list[float], list[float], list[float], list[float]] | None:
#             A tuple containing four lists of floats representing the Open, High, Low, and Close prices
#             for the given symbol and number of days, or None if the request fails.
#     """

#     url = "https://api.binance.com/api/v3/klines"
#     try:
#         r = requests.get(
#             url,
#             params={"symbol": symbol, "interval": "1d", "limit": days + 2},
#             timeout=10,
#             verify=certifi.where()
#         )
#         r.raise_for_status()
#         j = r.json()
#         if not j or not isinstance(j, list):
#             raise ValueError("Invalid OHLC data")
#         O = [float(x[1]) for x in j]
#         H = [float(x[2]) for x in j]
#         L = [float(x[3]) for x in j]
#         C = [float(x[4]) for x in j]
#         return O, H, L, C
#     except Exception as e:
#         logging.warning(f"binance_ohlc failed: {e}")

async def _fetch_binance_ohlc(
        symbol: str,
        days: int
    ) -> tuple[list[float], list[float], list[float], list[float]] | None:
    """
    Fetches the Binance OHLC data for the given symbol and number of days.

    Parameters:
        days (int): The number of days to fetch.

    Returns:
        tuple[list[float], list[float], list[float], list[float]] | None:
            A tuple containing four lists of floats representing the Open, High, Low, and Close prices
            for the given symbol and number of days, or None if the request fails.
    """

    url = "https://api.binance.com/api/v3/klines"
    try:
        async with httpx.AsyncClient(verify=certifi.where()) as client:
            res = await client.get(
                url,
                params={"symbol": symbol, "interval": "1d", "limit": days + 2},
                timeout=10
            )
            res.raise_for_status()
            j = res.json() if isinstance(res, httpx.Response) else await res.json()
            if not j or not isinstance(j, list):
                raise ValueError("Invalid OHLC data")
            O = [float(x[1]) for x in j]
            H = [float(x[2]) for x in j]
            L = [float(x[3]) for x in j]
            C = [float(x[4]) for x in j]
            return O, H, L, C
    except Exception as e:
        logging.warning(f"binance_ohlc failed: {e}")
    return None


async def get_realized_vol(
        days: int = 30,
        use_ewma: bool = True,
        lambda_: float = 0.97,
        annualize_days: int = 365
    ) -> float:
    """
    Fetches the realized volatility of the last 30 days from Binance and returns the latest value as a float.

    Parameters:
        days (int): Max age of the data point in days.
                    If the data point is older than this, 0.40 is returned.
        use_ewma (bool): Use exponential weighted moving average (EWMA) to smooth the realized volatilities.
        lambda_ (float): Parameter for the EWMA.
                         Default is 0.97.
        annualize_days (int): Number of days to annualize the realized volatility
                              (365 trading days per year).

    Returns:
        float: Calculated value of the realized volatility
        or 0.40 if less than 2 days of data are available.
    """

    url = "https://api.binance.com/api/v3/klines"
    try:
        async with httpx.AsyncClient(verify=certifi.where()) as client:
            res = await client.get(
                url,
                params={"symbol": "BTCUSDT", "interval": "1d", "limit": days + 1},  #todo: why base it on BTCUSDT?
                timeout=10
            )
            res.raise_for_status()
            if res.status_code != 200 or "json" not in (res.headers.get("Content-Type", "").lower()):
                return 0.40
            data = res.json() if isinstance(res, httpx.Response) else await res.json()
    except Exception:
        return 0.40
    closes = [float(x[4]) for x in data]
    if len(closes) < 2:
        return 0.40
    r = np.diff(np.log(closes))  # calculate the discrete difference of log prices
    p = 0.005  # 0.5% winsorization (clipping at the 0.5% and 99.5% quantiles)
    lo, hi = np.quantile(r, p), np.quantile(r, 1 - p)
    r = np.clip(r, lo, hi)
    if use_ewma:  # exponentially weighted moving average
        var = 0.0
        for ri in r[::-1]:
            var = lambda_ * var + (1 - lambda_) * (ri * ri)
        rv = np.sqrt(var)
    else:
        rv = float(np.std(r, ddof=1))
         # stddev scaled to annualized volatility
    return rv * np.sqrt(annualize_days)


