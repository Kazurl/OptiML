import logging
import os

import certifi
import httpx
import requests
import time
from datetime import datetime, timezone
from dotenv import load_dotenv

from binance_api.utils import (
    get_realized_vol,
)
from deribit_api.utils import (
    get_index_price
)
from utils.common_formulas import (
    get_risk_free_rate,
)
from utils.common_formulas import (
    implied_vol,
)
from utils.enums_option import (
    PRETTY_OPTION_TYPE,
)
from utils.options_formulas import (
    bs_greeks,
)
from utils.string_formatter import (
    fnum
)

load_dotenv()

DERIBIT_API_BASE = os.getenv("DERIBIT_API_BASE")


# === Temporary Cache Implementation ===
def _cget(store: dict, key, ttl: int):
    v = store.get(key)
    if not v:
        return None
    if time.time() - v["t"] > ttl:
        return None
    
    return v["data"]

def _cset(store: dict, key, data):
    store[key] = {"t": time.time(), "data": data}
    
    return data


async def get_option_instruments(base: str) -> list[dict] | None:
    """
    Robust fetch. Deribit wants 'expired' as lowercase string 'false'/'true'.
    Fetch list of option instruments for given base currency.

    Parameters:
        base (str): base currency e.g. "BTC"

    Returns:
        list of dict E.g.:
            {
                "price_index": "btc_usd",
                "kind": "option",
                "instrument_name": "BTC-1DEC25-84000-C",
                "maker_commission": 0.0003,
                "taker_commission": 0.0003,
                "instrument_type": "reversed",
                "expiration_timestamp": 1764576000000,
                "creation_timestamp": 1764231120000,
                "is_active": true,
                "tick_size": 0.0001,
                "contract_size": 1,
                "strike": 84000,
                "instrument_id": 556874,
                "min_trade_amount": 0.1,
                "option_type": "call",
                "block_trade_commission": 0.0003,
                "block_trade_min_trade_amount": 25,
                "block_trade_tick_size": 0.0001,
                "settlement_currency": "BTC",
                "settlement_period": "day",
                "base_currency": "BTC",
                "counter_currency": "USD",
                "quote_currency": "BTC",
                "tick_size_steps": [
                    {
                        "tick_size": 0.0005,
                        "above_price": 0.005
                    }
                ]
            }
        or [] if no results.
    """

    url = f"{DERIBIT_API_BASE}/public/get_instruments"
    base = base.upper()
    variants = [
        {"currency": base, "kind": "option", "expired": "false"},
        {"currency": base, "kind": "option"},
    ]
    for params in variants:
        try:
            async with httpx.AsyncClient(verify=certifi.where()) as client:
                res = await client.get(
                    url, params=params, timeout=12
                )
                res.raise_for_status()
                j = res.json() if isinstance(res, httpx.Response) else await res.json()
                if isinstance(j, dict) and "error" in j:
                    continue
                result = j.get("result", [])
                if result:
                    return result
        except Exception:
            continue
    return []


async def get_option_instruments_cached(
        base: str,
        cache: dict,
        ttl: int = 60
    ) -> list[dict] | None:
    """
    Cached version of get_option_instruments.

    Parameters:
        base (str): base currency e.g. "BTC"
        ttl (int): time to live in seconds
        cache (dict): cache to be used (_OPT_CACHE)

    Returns:
        list of dict E.g.:
            {
                "price_index": "btc_usd",
                "kind": "option",
                "instrument_name": "BTC-1DEC25-84000-C",
                "maker_commission": 0.0003,
                "taker_commission": 0.0003,
                "instrument_type": "reversed",
                "expiration_timestamp": 1764576000000,
                "creation_timestamp": 1764231120000,
                "is_active": true,
                "tick_size": 0.0001,
                "contract_size": 1,
                "strike": 84000,
                "instrument_id": 556874,
                "min_trade_amount": 0.1,
                "option_type": "call",
                "block_trade_commission": 0.0003,
                "block_trade_min_trade_amount": 25,
                "block_trade_tick_size": 0.0001,
                "settlement_currency": "BTC",
                "settlement_period": "day",
                "base_currency": "BTC",
                "counter_currency": "USD",
                "quote_currency": "BTC",
                "tick_size_steps": [
                    {
                        "tick_size": 0.0005,
                        "above_price": 0.005
                    }
                ]
            }
        or [] if no results.
    """
    base = base.upper()
    v = _cget(cache, base, ttl)
    if v is not None:
        return v
    data = await get_option_instruments(base)
    return _cset(cache, base, data)


async def get_book_summary_by_currency(
        base: str,
        kind: str = "option",
        ttl: int = 10
    ) -> tuple[list[dict], dict]:
    """
    Fetches summary of the book of instrument for a currency in bulk quotes.

    Parameters:
        base (str): base currency e.g. "BTC"
        kind (str): kind of instrument e.g. "option"
        ttl (int): time to live in seconds

    Returns:
        list and a dict keyed by instrument_name E.g.:
            {
                "BTC-27MAR26-300000-C": {
                                            "high": null,
                                            "low": null,
                                            "last": 0.0003,
                                            "instrument_name": "BTC-27MAR26-300000-C",
                                            "bid_price": 0.0002,
                                            "ask_price": 0.0005,
                                            "open_interest": 245.1,
                                            "mark_price": 0.00035746,
                                            "creation_timestamp": 1764492855227,
                                            "price_change": null,
                                            "interest_rate": 0,
                                            "volume": 0,
                                            "mark_iv": 70.92,
                                            "underlying_price": 92867.18,
                                            "underlying_index": "BTC-27MAR26",
                                            "estimated_delivery_price": 91262.37,
                                            "base_currency": "BTC",
                                            "quote_currency": "BTC",
                                            "volume_usd": 0,
                                            "mid_price": 0.00035
                                        },
                ...
            }
    """
    
    url = f"{DERIBIT_API_BASE}/public/get_book_summary_by_currency"
    try:
        async with httpx.AsyncClient(verify=certifi.where()) as client:
            res = await client.get(
                url,
                params={"currency": base.upper(), "kind": kind},
                timeout=12
            )
            res.raise_for_status()
            arr = res.json().get("result", []) if isinstance(res, httpx.Response) else await res.json().get("result", [])
    except Exception as e:
        logging.warning(f"get_book_summary_by_currency {base} {kind} failed: {e}")
        arr = []
    m = {x.get("instrument_name"): x for x in arr if "instrument_name" in x}

    return arr, m


async def get_ticker(instrument_name: str) -> dict | None:
    """
    Ticker info for a single instrument.

    Parameters:
        instrument_name (str): The instrument name to query. E.g. "BTC-30JUN23-30000-C"

    Returns:
        ticker info in dictionary form E.g.:
            {
                "instrument_name": "BTC-27DEC24",
                "state": "open",
                "settlement_price": 40250.5,
                "index_price": 40310.55,
                ...
            }
    """

    url = f"{DERIBIT_API_BASE}/public/ticker"
    
    try:
        async with httpx.AsyncClient(verify=certifi.where()) as client:
            res = await client.get(
                url,
                params={"instrument_name": instrument_name},
                timeout=10
            )
            data = res.json() if isinstance(res, httpx.Response) else await res.json()
            return data.get("result", {})
    except Exception as e:
        logging.warning(f"get_ticker {instrument_name} failed: {e}")
        return None
    

async def get_instrument(instrument_name: str) -> dict | None:
    """
    Instrument details for a single instrument.

    Parameters:
        instrument_name (str): The instrument name to query. E.g. "BTC-30JUN23-30000-C"

    Returns:
        instrument details in dictionary form E.g.:
            {
                "instrument_name": "BTC-27DEC24",
                "state": "open",
                "settlement_price": 40250.5,
                "index_price": 40310.55,
                ...
            }
        or {} if no results.
    """
    
    url = f"{DERIBIT_API_BASE}/public/get_instrument"
    try:
        async with httpx.AsyncClient(verify=certifi.where()) as client:
            res = await client.get(
                url,
                params={"instrument_name": instrument_name},
                timeout=10
            )
            data = res.json() if isinstance(res, httpx.Response) else await res.json()
            return data.get("result", {})
    except Exception as e:
        logging.warning(f"get_instrument {instrument_name} failed: {e}")
        return None
    

async def _get_last_trade_ts_ms(inst_name: str) -> int | None:
    
    """
    Get the last trade timestamp for an instrument in milliseconds.

    Parameters:
        inst_name (str): The instrument name to query. E.g. "BTC-30JUN23-30000-C"

    Returns:
        int | None: The timestamp (ms) of the last trade for the given instrument, or None if no results.
    """

    url = f"{DERIBIT_API_BASE}/public/get_last_trades_by_instrument"
    try:
        async with httpx.AsyncClient(verify=certifi.where()) as client:
            res = await client.get(
                url,
                params={
                    "instrument_name": inst_name,
                    "count": 1,
                    "include_old": "true"
                },
                timeout=8
            )
            res.raise_for_status()
            data = res.json().get("result", []) if isinstance(res, httpx.Response) else (await res.json()).get("result", [])
            if isinstance(data, dict) and "trades" in data:
                data = data["trades"]
            if isinstance(data, list) and data:
                ts = int(data[0].get("timestamp") or 0)
                return ts if ts > 0 else None
    except Exception as e:
        logging.warning(f"_get_last_trade_ts_ms {inst_name} failed: {e}")
        pass
    return None


def _pick_price_mid_last_mark(
        bid: float,
        ask: float,
        last: float,
        last_ts_ms: int,
        mark: float,
        staleness_sec: int = 300  # 5 minutes
    ) -> float | None:
    """
    Pick price in order of preference:
      1. mid of bid/ask if both present and >0
      2. last if present, >0, and not stale (within staleness_sec)
      3. mark if present and >0

    Parameters:
        bid (float): The bid price.
        ask (float): The ask price.
        last (float): The last trade price.
        last_ts_ms (int): The timestamp (ms) of the last trade.
        mark (float): The mark price.
        staleness_sec (int, optional): The staleness threshold in seconds. Defaults to 300 (5 minutes).

    Returns:
        float | None: The float price or None.
    """

    try:
        if bid and ask and bid > 0 and ask > 0:
            return float((float(bid) + float(ask)) / 2.0)
    except Exception:
        pass
    now_ms = int(time.time() * 1000)
    try:
        if last and last > 0 and last_ts_ms:
            if (now_ms - int(last_ts_ms)) <= staleness_sec * 1000:
                return float(last)
    except Exception as e:
        logging.warning(f"_pick_price_mid_last_mark failed: {e}")
        pass

    return float(mark or 0.0)


async def _unique_live_expiries(base: str, limit: int | None = None):
    """
    Returns a sorted list of unique future expiration timestamps (ms) for the given base.
    If limit is None, returns all expiries, otherwise returns the first limit expiries.
    # [IV surface + RV forecasting (HAR / GARCH)]

    Parameters:
        base (str): The base currency for the option.
        limit (int, optional): The maximum number of expiries to return.
                               If None, returns all expiries. Defaults to None.

    Returns:
        list: A sorted list of unique future expiration timestamps (ms).
    """
    
    arr = await get_option_instruments(base)
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    exps = sorted({
                    int(x["expiration_timestamp"]) for x in arr 
                        if x.get("expiration_timestamp") and
                        int(x["expiration_timestamp"]) > now_ms
                })
    return exps if limit is None else exps[:limit]


async def bs_greeks_wrapper(
        instrument_name: str,
        cache: dict | None = None
    ) -> tuple[dict | None, str | None]:
    """
    Wrapper to fetch data and compute Greeks for the given option instrument.

    Parameters:
        instrument_name (str): The option instrument name to query.
        cache (dict, optional): The cache to use for getting the risk-free rate. _RFR_CACHE

    Returns:
        tuple[dict | None, str | None]: A tuple containing the Greeks dictionary and an error message if failed.
            (greeks_dict, error_message)
                greek_dict has keys: underlying_price, strike, type, T, r, iv, fair_vol, g_mkt, g_fair
        or (None, error_message) if error.
    """

    ticker = await get_ticker(instrument_name)
    if not ticker:
        return None, "Invalid or unknown option instrument."
    underlying_price = ticker.get("underlying_price")
    if not underlying_price:
        return None, "Missing option data."
    inst = await get_instrument(instrument_name)
    if not inst:
        return None, "Instrument metadata missing."
    strike = float(inst.get("strike"))
    option_type = "call" if inst.get("option_type") == "call" else "put"
    expiry_ts = inst.get("expiration_timestamp")
    expiry = datetime.fromtimestamp(expiry_ts / 1000, tz=timezone.utc)
    T = max((expiry - datetime.now(timezone.utc)).days / 365, 0.0001)

    base = instrument_name.split("-")[0].upper()
    _arr, bm = await get_book_summary_by_currency(base, "option", ttl=8)
    from utils.crypto_options_formulas import _usd_option_mid
    usd_mid = await _usd_option_mid(inst, ticker, bm.get(instrument_name, {}), float(underlying_price))
    if usd_mid <= 0:
        return None, "Could not compute a valid mid/last/mark price."

    r = await get_risk_free_rate(cache=cache)
    iv = implied_vol(usd_mid, float(underlying_price), strike, T, r, option_type)
    fair_vol = await get_realized_vol(30)
    g_mkt = bs_greeks(float(underlying_price), strike, T, r, iv, option_type)
    g_fair = bs_greeks(float(underlying_price), strike, T, r, fair_vol, option_type)
    return {
        "underlying_price": underlying_price,
        "strike": strike,
        "type": option_type,
        "T": T,
        "r": r,
        "iv": iv,
        "fair_vol": fair_vol,
        "g_mkt": g_mkt,
        "g_fair": g_fair
    }, None


async def _find_atm_instruments_all_expiries(
        base: str,
        opt_type: str,
        cache_index: dict,
        cache_opt: dict
    ) -> tuple[list[dict], float | None]:
    """
    Finds ATM option instruments for ALL future expiries for the given base and option type.

    Parameters:
        base (str): The base currency (e.g. BTC).
        opt_type (str): The option type (e.g. "call" or "put").
        cache_index (dict): The cache for fetching index prices. (_INDEX_CACHE)
        cache_opt (dict): The cache for fetching option instruments. (_OPT_CACHE)

    Returns:
        tuple[list[dict], float | None]: A tuple containing a list of option instruments and the spot price.
            each dict has keys:
                date (e.g. "30JUN23"),
                tenor (days),
                strike,
                premium_usd,
                premium_coin,
                open_interest,
                instrument_name,
                underlying,
                quote_ccy
        or ([], None) if spot could not be fetched
    """

    base = base.upper()
    spot = await get_index_price(f"{base.lower()}_usd", cache=cache_index)
    if not spot:
        spot = await get_index_price(f"{base.lower()}_usdt", cache=cache_index)
    if not spot:
        return [], None
    
    spot = float(spot)
    instruments = await get_option_instruments_cached(base, cache=cache_opt)
    if not instruments:
        return [], spot
    
    by_expiry = {}
    now = datetime.now(timezone.utc)
    for inst in instruments:
        if inst.get("option_type") != opt_type:
            continue
        exp_ts = inst.get("expiration_timestamp")
        if not exp_ts:
            continue
        exp_dt = datetime.fromtimestamp(exp_ts / 1000, tz=timezone.utc)   # tz-aware
        if exp_dt <= now:
            continue
        by_expiry.setdefault(exp_ts, []).append(inst)
    _, bm = await get_book_summary_by_currency(base, "option", ttl=10)

    rows = []
    for exp_ts, insts in sorted(by_expiry.items()):
        closest = min(insts, key=lambda x: abs(float(x.get("strike", 0.0)) - spot))
        strike = float(closest["strike"])
        exp_dt = datetime.fromtimestamp(exp_ts / 1000, tz=timezone.utc)
        tenor_days = max((exp_dt - now).days, 0)
        name = closest["instrument_name"]
        summ = bm.get(name, {})
        bid = summ.get("bid_price"); ask = summ.get("ask_price")
        last = summ.get("last_price"); mark = summ.get("mark_price")
        last_ts = None
        if (not bid or bid <= 0 or not ask or ask <= 0) and last and last > 0:
            last_ts = await _get_last_trade_ts_ms(name)
        mid_raw = _pick_price_mid_last_mark(bid, ask, last, last_ts, mark)

        und = float(summ.get("underlying_price") or spot)
        quote_ccy = closest.get("quote_currency", "")
        if quote_ccy in ["USD", "USDC"]:
            prem_usd = mid_raw
            prem_coin = mid_raw / und if und > 0 else 0.0
        else:
            prem_usd = mid_raw * und
            prem_coin = mid_raw
        oi = int(summ.get("open_interest", 0) or 0)
        date_str = exp_dt.strftime("%d%b%y").upper()
        rows.append({
            "date": date_str,
            "tenor": tenor_days,
            "strike": strike,
            "premium_usd": float(prem_usd or 0.0),
            "premium_coin": float(prem_coin or 0.0),
            "open_interest": oi,
            "instrument_name": name,
            "underlying": und,
            "quote_ccy": quote_ccy
        })
    return rows, spot


async def _find_instruments_all_expiries(
        base: str,
        spot: float,
        cache_opt: dict,
        opt_type: str = "",
        is_only_fri: bool = True
    ) -> tuple[list[dict] | None, list[dict] | None]:
    """
    Finds option instruments for ALL future expiries for the given base and option type (optional).

    Parameters:
        base (str): The base currency (e.g. BTC)
        spot (float): The spot price of the underlying asset
        cache_opt (dict): The cache for fetching option instruments. (_OPT_CACHE)
        opt_type (str): The option type (e.g. "call" or "put"). Defaults to "" (both).
        is_only_fri (bool): Whether to only consider expiries on Fridays. Defaults to True.

    Returns:
        tuple[list[dict] | None, list[dict] | None]: A tuple containing two lists of option instruments.
            First list is for calls, second list is for puts.
            each dict has keys:
                date (e.g. "30JUN23"),
                tenor (days),
                strike,
                premium_usd,
                premium_coin,
                open_interest,
                instrument_name,
                underlying,
                quote_ccy
        or (None, None) if no instruments found or spot is None.
    """

    base = base.upper()
    instruments = await get_option_instruments_cached(base, cache=cache_opt)
    if not instruments or not spot:
        return None, None
    
    by_expiry = {}
    now = datetime.now(timezone.utc)
    for inst in instruments:
        if opt_type != "" and inst.get("option_type") != opt_type:
            continue
        exp_ts = inst.get("expiration_timestamp")
        if not exp_ts:
            continue
        exp_dt = datetime.fromtimestamp(exp_ts / 1000, tz=timezone.utc)   # tz-aware
        if exp_dt <= now or (is_only_fri and exp_dt.weekday() != 4):
            continue
        by_expiry.setdefault(exp_ts, []).append(inst)
    _, bm = await get_book_summary_by_currency(base, "option", ttl=10)

    calls_rows, puts_rows = [], []
    for exp_ts, insts in sorted(by_expiry.items()):
        for inst in insts:
            strike = float(inst["strike"])
            exp_dt = datetime.fromtimestamp(exp_ts / 1000, tz=timezone.utc)
            tenor_days = max((exp_dt - now).days, 0)
            name = inst["instrument_name"]
            summ = bm.get(name, {})
            bid = summ.get("bid_price")
            ask = summ.get("ask_price")
            last = summ.get("last_price")
            mark = summ.get("mark_price")
            last_ts = None
            if (not bid or bid <= 0 or not ask or ask <= 0) and last and last > 0:
                last_ts = await _get_last_trade_ts_ms(name)
            mid_raw = _pick_price_mid_last_mark(bid, ask, last, last_ts, mark)

            und = float(summ.get("underlying_price") or spot)
            quote_ccy = inst.get("quote_currency", "")
            if quote_ccy in ["USD", "USDC"]:
                prem_usd = mid_raw
                prem_coin = mid_raw / und if und > 0 else 0.0
            else:
                prem_usd = mid_raw * und
                prem_coin = mid_raw
            oi = int(summ.get("open_interest", 0) or 0)
            date_str = exp_dt.strftime("%d%b%y").upper()
            if inst.get("option_type") == "call":
                calls_rows.append({
                    "date": date_str,
                    "tenor": tenor_days,
                    "strike": strike,
                    "premium_usd": float(prem_usd or 0.0),
                    "premium_coin": float(prem_coin or 0.0),
                    "open_interest": oi,
                    "instrument_name": name,
                    "underlying": und,
                    "quote_ccy": quote_ccy
                })
            else:
                puts_rows.append({
                    "date": date_str,
                    "tenor": tenor_days,
                    "strike": strike,
                    "premium_usd": float(prem_usd or 0.0),
                    "premium_coin": float(prem_coin or 0.0),
                    "open_interest": oi,
                    "instrument_name": name,
                    "underlying": und,
                    "quote_ccy": quote_ccy
                })
    return calls_rows, puts_rows



# === Runs Strategy ===
async def _get_runs_common(
        base: str,
        action_symbol: str,
        opt_type: str,
        cache_index: dict,
        cache_opt: dict
    ) -> tuple[list, list, str, bool]:
    """
    Fetch all ATM instruments for the given base and opt_type.

    Parameters:
        base (str): base currency e.g. "BTC"/ "ETH"
        action_symbol (str): "B" for buy, "S" for sell
        opt_type (str): "call" or "put"
        cache_index (dict): cache for index prices (_INDEX_CACHE)
        cache_opt (dict): cache for option instruments (_OPT_CACHE)
    
    Returns:
        tuple[list, list, str, bool]: (raw data list, processed data list, telegram msg string, is_error bool)
            raw data list: list of lists with fields:
                [date, tenor, strike, action_symbol, type, premium_usd, premium_coin, open_interest]
            processed data list: list of lists with fields:
                [date, tenor, strike, action_symbol, type, premium_usd, premium_coin, open_interest]
            telegram msg string: a string in Markdown format
            is_error bool: True if there was an error, False otherwise
    """

    rows, spot = await _find_atm_instruments_all_expiries(base, opt_type, cache_index, cache_opt)
    if rows == [] and spot is None:  # spot fetch failed
        return [], [], f"Could not fetch spot for {base}.", True
    if not rows:  # no expiries found
        return [], [], f"No expiries found for {base} {opt_type}s.", True
    # format and send the message to user
    coin_sym = base
    header = (
        f"*{base} {('Buy' if action_symbol=='B' else 'Sell')} {opt_type.capitalize()} — ATM by Expiry*\n"
        f"Spot: {spot:,.2f} USD\n"
        "```\n"
        f"{'Date':<9} {'DTE':>3} {'Strike':>9} {'B/S':>3} {'Type':>4} "
        f"{'USD':>10} {coin_sym:>8} {'OI':>6}\n"
        f"{'-'*9} {'-'*3:>3} {'-'*9:>9} {'-'*3:>3} {'-'*4:>4} "
        f"{'-'*10:>10} {'-'*8:>8} {'-'*6:>6}\n"
    )
    raw, processed, body = [], [], ""
    for r in rows:
        raw.append([r['date'], r['tenor'], r['strike'], action_symbol, ('C' if opt_type=='call' else 'P'),
                    r['premium_usd'], r['premium_coin'], r['open_interest']])
        processed.append([r['date'], r['tenor'], fnum(r['strike'], 0), action_symbol, ('C' if opt_type=='call' else 'P'),
                          fnum(r['premium_usd']), fnum(r['premium_coin'], 6), f"{r['open_interest']}"])
        body += (
            f"{r['date']:<9} {r['tenor']:>3} {r['strike']:>9,.0f} {action_symbol:>3} {('C' if opt_type=='call' else 'P'):>4} "
            f"{r['premium_usd']:>10,.2f} {r['premium_coin']:>8,.6f} {r['open_interest']:>6}\n"
        )
    msg = header + body + "```"
    return raw, processed, msg, False


async def _get_all_expiries(
        base: str,
        cache_opt: dict,
        cache_index: dict,
        opt_type: str = "",
        is_only_fri: bool = True
    ) -> tuple[tuple[list, list, str], tuple[list, list, str], bool]:
    """
    Finds all option instruments for the given base and opt_type (CALL or PUT) for all expiries.

    Parameters:
        base (str): The base currency (e.g. BTC)
        cache_opt (dict): The cache for fetching option instruments. (_OPT_CACHE)
        cache_index (dict): The cache for fetching index prices. (_INDEX_CACHE)
        opt_type (str): The option type (e.g. "call" or "put"). Defaults to "" (both).
        is_only_fri (bool): Whether to only consider expiries on Fridays. Defaults to True.

    Returns:
        tuple[tuple[list, list, str], tuple[list, list, str], bool]: A tuple containing two tuples of lists and a bool.
            first tuple: raw data list of lists with fields:
                [date, tenor, strike, action_symbol, type, premium_usd, premium_coin, open_interest]
            second tuple: processed data list of lists with fields:
                [date, tenor, strike, action_symbol, type, premium_usd, premium_coin, open_interest]
            bool: whether the function encountered an error
        or (None, None, msg), (None, None, msg), True if spot/instruments could not be fetched
    """

    # get spot first
    base = base.upper()
    spot = await get_index_price(f"{base.lower()}_usd", cache=cache_index)
    if not spot:
        spot = await get_index_price(f"{base.lower()}_usdt", cache=cache_index)
    if not spot:
        err_msg = f"Could not fetch spot for {base}."
        return ([], [], err_msg), ([], [], err_msg), True
    
    spot = float(spot)
    call_insts, put_insts = await _find_instruments_all_expiries(base, spot, cache_opt, opt_type, is_only_fri)
    if not call_insts and not put_insts:
        err_msg = f"No expiries found for {base}."
        return ([], [], err_msg), ([], [], err_msg), True
    
    # format and send the message to user
    coin_sym = base
    def header_generator(opt_type: str) -> str:
        return (
            f"*{base} by {'All' if not is_only_fri else 'Friday'} Expiries ({opt_type})*\n"
            f"Spot: {spot:,.2f} USD\n"
            "```\n"
            f"{'Date':<9} {'DTE':>3} {'Strike':>9} {'Type':>4} "
            f"{'USD':>10} {coin_sym:>8} {'OI':>6}\n"
            f"{'-'*9} {'-'*3:>3} {'-'*9:>9} {'-'*4:>4} "
            f"{'-'*10:>10} {'-'*8:>8} {'-'*6:>6}\n"
        )

    calls_raw, calls_processed, calls_header, calls_body = [], [], header_generator(PRETTY_OPTION_TYPE.CALL.value), ""
    puts_raw, puts_processed, puts_header, puts_body = [], [], header_generator(PRETTY_OPTION_TYPE.PUT.value), ""
    # CALLS
    if not call_insts:
        calls_msg = f"No calls found for {base}."
    else:
        for r in call_insts:
            calls_raw.append([r['date'], r['tenor'], r['strike'], 'C',
                        r['premium_usd'], r['premium_coin'], r['open_interest']])
            calls_processed.append([r['date'], r['tenor'], fnum(r['strike'], 0), 'C',
                            fnum(r['premium_usd']), fnum(r['premium_coin'], 6), f"{r['open_interest']}"])
            calls_body += (
                f"{r['date']:<9} {r['tenor']:>3} {r['strike']:>9,.0f} {'C':>4} "
                f"{r['premium_usd']:>10,.2f} {r['premium_coin']:>8,.6f} {r['open_interest']:>6}\n"
            )
        calls_msg = calls_header + calls_body + "```"

    # PUTS
    if not put_insts:
        puts_msg = f"No puts found for {base}."
    else:
        for r in put_insts:
            puts_raw.append([r['date'], r['tenor'], r['strike'], 'P',
                        r['premium_usd'], r['premium_coin'], r['open_interest']])
            puts_processed.append([r['date'], r['tenor'], fnum(r['strike'], 0), 'P',
                            fnum(r['premium_usd']), fnum(r['premium_coin'], 6), f"{r['open_interest']}"])
            puts_body += (
                f"{r['date']:<9} {r['tenor']:>3} {r['strike']:>9,.0f} {'P':>4} "
                f"{r['premium_usd']:>10,.2f} {r['premium_coin']:>8,.6f} {r['open_interest']:>6}\n"
            )
        puts_msg = puts_header + puts_body + "```"

    return (calls_raw, calls_processed, calls_msg), (puts_raw, puts_processed, puts_msg), False