from datetime import datetime, timezone

from deribit_api.options import (
    _get_last_trade_ts_ms,
    _pick_price_mid_last_mark
)
from utils.common_formulas import (
    implied_vol,
)

async def _usd_option_mid(
        inst: dict,
        ticker: dict | None,
        summary: dict | None,
        spot_fallback: float
    ) -> float:
    """
    Calculates the USD-converted mid-price for an option, regardless of settlement currency using ticker bid/ask (prefer), otherwise last (if fresh), otherwise mark.
    handles coin vs USD quotes.
    If quote is not USD/USDC, convert using spot_usd.

    Parameters:
        inst (dict): instrument dictionary
        ticker (dict | None): ticker dictionary or None
        summary (dict | None): summary dictionary or None
        spot_fallback (float): fallback spot value to use if underlying price not found

    Returns:
        float: USD mid value (result is always a USD-equivalent price)
    """
    
    quote = inst.get("quote_currency", "").upper()
    und = float(
            (ticker or {}).get("underlying_price") or
            (summary or {}).get("underlying_price") or
            spot_fallback or 0.0
        )
    bid = (ticker or {}).get("best_bid_price")
    ask = (ticker or {}).get("best_ask_price")
    last = (ticker or {}).get("last_price")
    mark = (ticker or {}).get("mark_price")
    if not bid and summary: bid = summary.get("bid_price")
    if not ask and summary: ask = summary.get("ask_price")
    if (not last or last <= 0) and summary: last = summary.get("last_price")
    if (not mark or mark <= 0) and summary: mark = summary.get("mark_price")

    last_ts = None
    try:
        if not (bid and ask and bid > 0 and ask > 0) and last and last > 0:
            inst_name = inst.get("instrument_name")
            if inst_name:
                last_ts = await _get_last_trade_ts_ms(inst_name)
    except Exception:
        last_ts = None

    raw_px = _pick_price_mid_last_mark(bid, ask, last, last_ts, mark)
    if quote in ["USD", "USDC"]:
        return float(raw_px or 0.0)
    
    # If the quote currency is not USD/USDC,
    # multiplies the mid by the spot price of the underlying
    return float((raw_px * und) if (raw_px and und) else 0.0)


async def _raw_option_mid(
        inst: dict,
        ticker: dict | None,
        summary: dict | None
    ) -> float:
    """
    Calculates a raw mid-price for the option, in its native quote currency (e.g., BTC, ETH, USD)
    using ticker bid/ask (prefer), otherwise last (if fresh), otherwise mark.
    Does not convert or adjust based on spot price or underlying USD value.

    Parameters:
        inst (dict): instrument dictionary
        ticker (dict | None): ticker dictionary or None
        summary (dict | None): summary dictionary or None

    Returns:
        float: raw mid value
    """

    bid = (ticker or {}).get("best_bid_price")
    ask = (ticker or {}).get("best_ask_price")
    last = (ticker or {}).get("last_price")
    mark = (ticker or {}).get("mark_price")
    if not bid and summary: bid = summary.get("bid_price")
    if not ask and summary: ask = summary.get("ask_price")
    if (not last or last <= 0) and summary: last = summary.get("last_price")
    if (not mark or mark <= 0) and summary: mark = summary.get("mark_price")

    last_ts = None
    try:
        if not (bid and ask and bid > 0 and ask > 0) and last and last > 0:
            inst_name = inst.get("instrument_name")
            if inst_name:
                last_ts = await _get_last_trade_ts_ms(inst_name)
    except Exception:
        last_ts = None

    return float(_pick_price_mid_last_mark(bid, ask, last, last_ts, mark) or 0.0)


def _usd_mid_from_summary_for_inst(inst: dict, summ: dict, spot_usd: float) -> float:
    """
    USD mid using summary bid/ask (prefer), otherwise mark; handles coin vs USD quotes.
    If quote is not USD/USDC, convert using spot_usd to get market USD value.
    # [IV surface + RV forecasting (HAR / GARCH)]

    Parameters:
        inst (dict): instrument dictionary
        summ (dict): summary dictionary
        spot_usd (float): spot price of the underlying

    Returns:
        float: market USD mid value
    """

    bid = float(summ.get("bid_price") or 0.0)
    ask = float(summ.get("ask_price") or 0.0)
    mark = float(summ.get("mark_price") or 0.0)
    mid_raw = ((bid + ask) / 2.0) if (bid > 0 and ask > 0) else (mark if mark > 0 else 0.0)
    und = float(summ.get("underlying_price") or spot_usd or 0.0)
    q = inst.get("quote_currency", "").upper()

    res = 0.0
    if q in ("USD", "USDC"):  # direct USD quote using summary mid
        res = mid_raw
    else:  # non-USD quote; convert using spot to get market USD value
        res = (mid_raw * und) if (mid_raw > 0 and und > 0) else 0.0
    return res 


def _build_iv_surface_for_expiry(
        base: str,
        expiry_ts: int,
        spot_usd: float,
        r: float,
        moneyness_band: float,
        bm: dict,
        inst_map: dict
    ) -> list[dict]:
    
    """
    Builds a list of implied volatilities for options with the given expiry timestamp (ms).
        i.e. IV surface rows for the given expiry timestamp (ms) where each row is a
             dict with keys: name, K, type, T, iv, usd_mid
    Only considers strikes within [spot_usd*(1-moneyness_band), spot_usd*(1+moneyness_band)].
    # [IV surface + RV forecasting (HAR / GARCH)]

    Parameters:
        base (str): base currency
        expiry_ts (int): expiry timestamp (ms)
        spot_usd (float): spot price of the underlying
        r (float): risk-free rate
        moneyness_band (float): moneyness band
        bm (dict): bid/ask summary
        inst_map (dict): instrument map

    Returns:
        list[dict]: list of implied volatilities
    """
    now = datetime.now(timezone.utc)
    T = max((datetime.fromtimestamp(expiry_ts/1000, tz=timezone.utc) - now).total_seconds() / (365*24*3600), 1e-6)

    rows = []
    lower, upper = spot_usd*(1-moneyness_band), spot_usd*(1+moneyness_band)

    for name, inst in inst_map.items():
        if int(inst.get("expiration_timestamp", 0)) != int(expiry_ts):
            continue
        K = float(inst.get("strike") or 0.0)
        if K <= 0 or not (lower <= K <= upper):
            continue
        summ = bm.get(name, {}) or {}
        usd_mid = _usd_mid_from_summary_for_inst(inst, summ, spot_usd)
        if usd_mid <= 0:
            continue
        typ = "call" if inst.get("option_type") == "call" else "put"
        iv = implied_vol(usd_mid, spot_usd, K, T, r, typ)
        if not (0.0001 <= iv <= 5.0):
            continue
        rows.append({"name": name, "K": K, "type": typ, "T": T, "iv": iv, "usd_mid": usd_mid})
    return rows

