import logging
import requests
import math
import time
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv
from scipy.stats import norm
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
import numpy as np
import pandas as pd
import certifi
import os, csv, io, sys

from deribit_api.options import (
    bs_greeks_wrapper,
    get_book_summary_by_currency,
    get_instrument,
    get_option_instruments_cached,
    get_ticker,
    _get_last_trade_ts_ms,
    _get_runs_common,
    _get_all_expiries,
    _pick_price_mid_last_mark,
    _unique_live_expiries,
)
from deribit_api.utils import (
    _get_deribit_index_usd_first,
    get_index_price,
    _pick_min_spot_index,
)
from utils.common_formulas import(
    implied_vol,
    get_realized_vol_yz_dynamic,
    get_risk_free_rate,
    _forecast_rv_annualized,
    _zscore_list,
)
from utils.enums_option import (
    PRETTY_OPTION_TYPE, PRETTY_PARAMETERS, PRETTY_RUNS_TYPE
)
from utils.crypto_options_formulas import (
    _build_iv_surface_for_expiry,
    _raw_option_mid,
    _usd_mid_from_summary_for_inst,
    _usd_option_mid,
)
from utils.options_formulas import (
    bs_itm_probability,
    bs_price,
)
from utils.string_formatter import (
    fnum, pct, fpct,
)

load_dotenv()

"""
export PYTHONPATH=$(pwd)
python app/pages/crypto_viewer/deribit.py
"""

# Force requests to a working CA bundle (Windows-safe)
os.environ["SSL_CERT_FILE"] = certifi.where()
os.environ["REQUESTS_CA_BUNDLE"] = certifi.where()

# === CONFIG ===
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
DERIBIT_API_BASE = os.getenv("DERIBIT_API_BASE")

# === LOGGING ===
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
print("LOGGING SETUP COMPLETE")
logging.debug("DEBUG logging ready")
logging.info("INFO logging ready")
logging.warning("WARNING logging ready")

# ========== Pretty formatting helper ==========
def _kv(label: str, value: str, lw: int = 18, vw: int = 12) -> str:
    return f"{label:<{lw}}: {value:>{vw}}"

# ========= Simple in-memory caches (TTL) =========
# todo: redis cache implementation
_OPT_CACHE = {}          # key: base -> {t: ts, data: [...]}
_BOOK_CACHE = {}         # key: (base, kind) -> {t: ts, data: [...]}
_INDEX_CACHE = {}        # key: index_name -> {t: ts, price: float}
_RFR_CACHE = {"t": 0.0, "val": None}  # cache RFR to avoid noisy refetches

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

# # === RISK-FREE RATE with robust fallbacks ===
# def _yahoo_irx_rate(max_age_days: int = 30, retries: int = 2, backoff: float = 0.7) -> float | None:
#     """
#     Get the the latest RFR from Yahoo Finance.
#         max_age_days: maximum age of cached data in days
#         retries: number of fetch retries
#         backoff: backoff factor after each unsuccessful retry
#     Returns RFR if successful, else None if data points are not available or too old.
#     """
#     url = "https://query1.finance.yahoo.com/v8/finance/chart/%5EIRX"  # ^IRX = 3-month T-bill
#     params = {"range": "3mo", "interval": "1d"}  # get last 3 months daily data; daily bars
#     headers = {"User-Agent": "Mozilla/5.0"}  # to avoid beig blocked as a bot when requesting
#     delay = backoff
#     for _ in range(max(1, retries)):
#         """
#         Model:
#         Grab the last 90 days' data of closed prices and find the first valid close to be used as the RFR.
#         Sanity: Reasonably sound for normal daily/weekly options service using tele bots. 
#                 For HFT, use more sophisticated direct market data (e.g. median or weighted average).
#         """
#         try:
#             r = requests.get(url, params=params, headers=headers, timeout=12, verify=certifi.where())
#             r.raise_for_status()
#             ct = r.headers.get("Content-Type", "").lower()
#             if r.status_code != 200 or "json" not in ct:
#                 logging.info(f"RFR Yahoo ^IRX skipped (status={r.status_code}, ct={ct})")
#                 return None
#             j = r.json()
#             res = j.get("chart", {}).get("result", [])
#             if not res:
#                 logging.info("RFR Yahoo ^IRX empty result set")
#                 return None
#             q = res[0].get("indicators", {}).get("quote", [])
#             closes = q[0].get("close", []) if q else []
#             ts = res[0].get("timestamp", [])
#             if not closes or not ts:
#                 logging.info("RFR Yahoo ^IRX missing closes/timestamps")
#                 return None
#             today = datetime.now(timezone.utc).date()

#             # yahoo returns T-bills as annualized percentage e.g. 5.30%, not decimals
#             for i in range(len(closes) - 1, -1, -1):
#                 c = closes[i]
#                 if c is None:
#                     continue
#                 dt = datetime.fromtimestamp(ts[i], tz=timezone.utc).date()
#                 if (today - dt).days <= max_age_days:
#                     val = float(c) / 100.0  # convert to decimals
#                     if 0.0 <= val <= 0.15:
#                         logging.info(f"RFR Yahoo ^IRX {dt.isoformat()} -> {val*100:.2f}%")
#                         return val
#             return None
#         except Exception as e:
#             logging.info(f"RFR Yahoo ^IRX attempt failed: {e}")
#         time.sleep(delay)
#         delay *= 2
#     return None

# def _fred_dgs3mo_csv(max_age_days: int = 30) -> float | None:
#     """
#     Fetches the 3-Month Treasury Constant Maturity Rate (Annualized) from FRED and returns the latest value as a float.
#         max_age_days: Max age of the data point in days. If the data point is older than this, None is returned.
#         Returns latest value of the 3-Month Treasury Constant Maturity Rate (Annualized), or None no data point or all too old.
#     """
#     try:
#         url = "https://fred.stlouisfed.org/graph/fredgraph.csv"
#         r = requests.get(url, params={"id": "DGS3MO"}, timeout=12, verify=certifi.where())  # 3-Month Treasury Constant Maturity Rate (Annualized)
#         r.raise_for_status()
#         today = datetime.now(timezone.utc).date()
#         rows = list(csv.reader(io.StringIO(r.text)))
#         for row in reversed(rows[1:]):
#             if len(row) < 2:
#                 continue
#             #d, v = row[0], row[1]  # todo: remove if works
#             d, v = row
#             if not v or v == ".":
#                 continue
#             dt = datetime.fromisoformat(d).date()
#             if (today - dt).days > max_age_days:
#                 continue
#             # fred returns T-bills as annualized percentage e.g. 5.30%, not decimals
#             val = float(v) / 100.0
#             if 0.0 <= val <= 0.15:
#                 logging.warning(f"RFR FRED DGS3MO {d} -> {val*100:.2f}%")
#                 return val
#     except Exception as e:
#         logging.warning(f"RFR FRED DGS3MO failed: {e}")
#     return None

# def _treasury_yield_curve_csv(max_age_days: int = 30) -> float | None:
#     """
#     Fetches the 3-Month Treasury Constant Maturity Rate (Annualized) from FRED and returns the latest value as a float.
#         max_age_days: Max age of the data point in days. If the data point is older than this, None is returned.
#         Returns latest value of the 3-Month Treasury Constant Maturity Rate (Annualized), or None if the data point is too old.
#     """
#     try:
#         url = "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/Daily_Treasury_Yield_Curve_Rates.csv"
#         r = requests.get(url, timeout=12, verify=certifi.where())
#         r.raise_for_status()

#         today = datetime.now(timezone.utc).date()
#         print(r.text)
#         reader = csv.DictReader(io.StringIO(r.text))
#         for row in reversed(list(reader)):  # reversed to get most recent
#             d = row.get("Date")
#             v = row.get("3 Mo")
#             if not d or not v:
#                 continue
#             try:
#                 dt = datetime.strptime(d, "%m/%d/%Y").date()
#             except ValueError:
#                 try:
#                     dt = datetime.strptime(d, "%Y-%m-%d").date()
#                 except Exception:
#                     continue
#             if v in ("", "N/A"):
#                 continue
#             if (today - dt).days > max_age_days:
#                 continue
#             val = float(v) / 100.0
#             if 0.0 <= val <= 0.15:
#                 logging.warning(f"RFR Treasury CSV {dt.isoformat()} -> {val*100:.2f}%")
#                 return val
#     except Exception as e:
#         logging.warning(f"RFR Treasury CSV failed: {e}")
#     return None

# === REALIZED VOL (BINANCE, no key) ===

# # === Realized Vol: Yang–Zhang (OHLC), adaptive by DTE ===


# === API HELPERS ===
# todo: relook after normal options completed
def get_futures_instruments(base: str) -> list[dict] | None:
    """
    Fetch list of future instruments fro Deribit.
    Return list of dict E.g.:
        {
            "kind": "future",
            "base_currency": "BTC",
            "currency": "USD",
            "min_trade_amount": 10.0,
            "instrument_name": "BTC-27DEC24",
            "is_active": true,
            "settlement_period": "month",
            "created": "2024-01-12 00:00:00 GMT",
            "tick_size": 0.5,
            "price_precision": 1,
            "expiration_timestamp": 1735267200000,
            "contract_size": 10,
            "strike": null,
            "option_type": null
        }
    """
    url = f"{DERIBIT_API_BASE}/public/get_instruments"
    try:
        res = requests.get(
                url,
                params={"currency": base.upper(), "kind": "future"},
                timeout=10,
                verify=certifi.where()
            )
        res.raise_for_status()
        data = res.json()
        return data.get("result", [])
    except Exception as e:
        logging.warning(f"get_futures_instruments {base} failed: {e}")

# ---------- PRICE SELECTION HELPERS (MID → LAST(if fresh) → MARK) ----------
STALE_LAST_SECONDS = 300  # 5 minutes

# NEW: spot reference for /basis (PERPETUAL mid→last(fresh)→mark, else lowest index)
async def get_spot_reference(
        base: str, stale_sec: int = STALE_LAST_SECONDS
    ) -> tuple[float | None, str]:
    """
    Spot reference price for /basis:
      1. PERPETUAL future mid if both bid/ask >0
      2. PERPETUAL last if within stale_sec
      3. PERPETUAL mark if >0
      4. lowest available index among USD/USDT/USDC
      Returns (price, label) or (None, "n/a") if none found.
    """
    # Try the PERPETUAL future first
    _, futmap = await get_book_summary_by_currency(base, "future", ttl=5)
    perp = next((n for n in futmap.keys() if "PERPETUAL" in n.upper()), None)
    if perp:
        s = futmap.get(perp, {}) or {}
        bid = float(s.get("bid_price") or 0.0)
        ask = float(s.get("ask_price") or 0.0)
        if bid > 0 and ask > 0:
            return (bid + ask) / 2.0, "Perp (mid)"

        last = s.get("last_price")
        if last:
            ts = await _get_last_trade_ts_ms(perp)
            if ts:
                age = (datetime.now(timezone.utc) - datetime.fromtimestamp(ts / 1000, tz=timezone.utc)).total_seconds()
                if age <= stale_sec:
                    return float(last), "Perp (last)"

        mark = s.get("mark_price")
        if mark:
            return float(mark), "Perp (mark)"

    # Fallback: choose the lowest available index (USD/USDT/USDC)
    idx, ccy = await _pick_min_spot_index(base, cache=_INDEX_CACHE)
    if idx is not None:
        return float(idx), f"Index {ccy}"
    return None, "n/a"

# ========= IV surface + RV forecasting (HAR / GARCH) =========


# ---- Daily realized-vol series (Yang–Zhang style per-day proxy) ----



# ---- HAR forecast (next-day, annualized) ----

# ---- GARCH(1,1) forecast (next-day, annualized; simple calibration) ----

# === BLACK–SCHOLES HELPERS ===

# === RUNS (ATM per ALL expiries) ===

# async def _runs_common(update: Update, context: ContextTypes.DEFAULT_TYPE, action_symbol: str, opt_type: str) -> None:
#     """
#     Common handler for /run{b|s}{c|p} commands.
#     action_symbol: "B" or "S"
#     opt_type: "call" or "put"
#     """
#     # Try to determine base from args; default to BTC
#     base = "BTC"
#     if context.args and context.args[0].upper() in ["BTC", "ETH"]:
#         base = context.args[0].upper()
#     # fetch ATM instruments for all expiries for the given base and opt_type
#     rows, spot = _find_atm_instruments_all_expiries(base, opt_type)
#     if rows == [] and spot is None:  # spot fetch failed
#         await update.message.reply_text(f"Could not fetch spot for {base}.")
#         return
#     if not rows:  # no expiries found
#         await update.message.reply_text(f"No expiries found for {base} {opt_type}s.")
#         return
#     # format and send the message to user
#     coin_sym = base
#     header = (
#         f"*{base} {('Buy' if action_symbol=='B' else 'Sell')} {opt_type.capitalize()} — ATM by Expiry*\n"
#         f"Spot: {spot:,.2f} USD\n"
#         "```\n"
#         f"{'Date':<9} {'DTE':>3} {'Strike':>9} {'B/S':>3} {'Type':>4} "
#         f"{'USD':>10} {coin_sym:>8} {'OI':>6}\n"
#         f"{'-'*9} {'-'*3:>3} {'-'*9:>9} {'-'*3:>3} {'-'*4:>4} "
#         f"{'-'*10:>10} {'-'*8:>8} {'-'*6:>6}\n"
#     )
#     body = ""
#     for r in rows:
#         body += (
#             f"{r['date']:<9} {r['tenor']:>3} {r['strike']:>9,.0f} {action_symbol:>3} {('C' if opt_type=='call' else 'P'):>4} "
#             f"{r['premium_usd']:>10,.2f} {r['premium_coin']:>8,.6f} {r['open_interest']:>6}\n"
#         )
#     msg = header + body + "```"
#     await update.message.reply_text(msg, parse_mode="Markdown")

async def _runs_common(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        action_symbol: str,
        opt_type: str
    ) -> None:
    """
    Common handler for /run{b|s}{c|p} commands.
    action_symbol: "B" or "S"
    opt_type: "call" or "put"
    """
    # Try to determine base from args; default to BTC
    base = "BTC"
    if context.args and context.args[0].upper() in ["BTC", "ETH"]:
        base = context.args[0].upper()
        
    _, _, msg, is_error = await _get_runs_common(base, action_symbol, opt_type, _INDEX_CACHE, _OPT_CACHE)
    if is_error:
        await update.message.reply_text(msg)
        return
    await update.message.reply_text(msg, parse_mode="Markdown")


async def _get_run(
        base: str,
        action_symbol: str,
        opt_type: str
    ) -> tuple[list, list, str]:
    """
    Fetch ATM instruments for the given base and opt_type.

    Parameters:
        base (str): base currency e.g. "BTC"/ "ETH"
        action_symbol (str): "B" for buy, "S" for sell
        opt_type (str): "call" or "put"
    
    Returns:
        tuple[list, str]: (processed_data, msg, is_error)
            raw_data: list of rows with fields:
                [date, tenor, strike, action_symbol, type, premium_usd, premium_coin, open_interest]
            msg: telegram msg string
    """
    raw_data, processed_data, msg, _ = await _get_runs_common(base, action_symbol, opt_type, _INDEX_CACHE, _OPT_CACHE)
    return raw_data, processed_data, msg


async def _get_all_runs(base: str) -> dict[tuple[list, list, str, bool]]:
    """
    Get all 4 runs (sell call, sell put, buy call, buy put) for the given base.
    Returns (runs_raw_dict, runs_processed_dict, msg, is_error) where runs_dict has keys:
        'Sell Call', 'Sell Put', 'Buy Call', 'Buy Put'
    Each value is a tuple of raw data list, processed data list, telegram msg string, is_error bool
        The data list has rows with fields:
            [date, tenor, strike, action_symbol, type, premium_usd, premium_coin, open_interest]
    i.e (raw_data, proc_data, msg, False) if success,
    or ([], [], msg, True) if error.
    """
    runs = {}
    runs_types = [
                    ("S", "call", PRETTY_RUNS_TYPE.SELL_CALL.value),
                    ("S", "put", PRETTY_RUNS_TYPE.SELL_PUT.value),
                    ("B", "call", PRETTY_RUNS_TYPE.BUY_CALL.value),
                    ("B", "put", PRETTY_RUNS_TYPE.BUY_PUT.value)
                ]
    for action_symbol, opt_type, key in runs_types:
        raw, processed, msg, is_error = await _get_runs_common(base, action_symbol, opt_type, _INDEX_CACHE, _OPT_CACHE)
        runs[key] = (raw, processed, msg, is_error)
    return runs


async def runsc(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /runsc [BTC|ETH] - Show Sell Call runs for ALL expiries (ATM strikes)
    """

    await _runs_common(update, context, action_symbol="S", opt_type="call")

async def runsp(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /runsp [BTC|ETH] - Show Sell Put runs for ALL expiries (ATM strikes)
    """
    await _runs_common(update, context, action_symbol="S", opt_type="put")

async def runbc(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /runbc [BTC|ETH] - Show Buy Call runs for ALL expiries (ATM strikes)
    """
    await _runs_common(update, context, action_symbol="B", opt_type="call")

async def runbp(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /runbp [BTC|ETH] - Show Buy Put runs for ALL expiries (ATM strikes)
    """
    await _runs_common(update, context, action_symbol="B", opt_type="put")

async def all_runs(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /allruns [BTC|ETH] - Show all runs for ALL expiries (ATM strikes)
    """
    # Try to determine base from args; default to BTC
    base = "BTC"
    if context.args and context.args[0].upper() in ["BTC", "ETH"]:
        base = context.args[0].upper()
        
    runs = await _get_all_runs(base)
    for run_type, (raw_data, processed_data, msg, is_error) in runs.items():
        if is_error:
            await update.message.reply_text(msg)
            continue
        await update.message.reply_text(msg, parse_mode="Markdown")

async def allrunsexp(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /allrunsexp [BTC|ETH] [C|P] [T|F]- Show runs for all expiries (Fridays only by default)
    """
    # Try to determine base from args; default to BTC
    base, opt_type, is_fri_only = "BTC", "", True
    if context.args:
        if context.args[0].upper() in ["BTC", "ETH"]:
            base = context.args[0].upper()
        if len(context.args) > 1 and context.args[1].upper() in ["C", "P"]:
            opt_type = "call" if context.args[1].upper() == "C" else "put"
        if len(context.args) > 2 and context.args[2].upper() in ["T", "F"]:
            is_fri_only = context.args[2].upper() == "T"

    (_, _, calls_msg), (_, _, puts_msg), is_error = await _get_all_expiries(
        base, _OPT_CACHE, _INDEX_CACHE, opt_type, is_fri_only
    )

    if is_error:
        await update.message.reply_text(calls_msg)
        return

    MAX_LEN = 4000  # a bit below 4096 to be safe

    async def send_message_in_chunks(chat_id: int, text: str) -> None:
        if not text:
            return

        lines = text.split("\n")
        header_lines = []
        body_lines = []
        in_header = True

        for line in lines:
            # Everything up to and including the opening ``` stays in the header
            if in_header:
                header_lines.append(line)
                if line.strip().startswith("```"):
                    in_header = False
            else:
                body_lines.append(line)

        header = "\n".join(header_lines).rstrip("\n")
        body = "\n".join(body_lines).rstrip("\n")

        # First message: header + as much of body as fits, keeping code fence closed
        current = header + "\n"
        current_len = len(current)

        for line in body.split("\n"):
            # +1 for the newline
            if current_len + len(line) + 1 > MAX_LEN:
                # Close the code block and send
                current += "\n```"
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=current,
                    parse_mode="Markdown",
                )
                # Start a new code block chunk (no bold header now, just fenced table)
                current = "```"
                current_len = len(current)
            else:
                current += "\n" + line
                current_len += len(line) + 1

        if current.strip():
            # Ensure the last chunk is properly closed
            if not current.rstrip().endswith("```"):
                current += "\n```"
            await context.bot.send_message(
                chat_id=chat_id,
                text=current,
                parse_mode="Markdown",
            )


    if opt_type != "put":
        await send_message_in_chunks(update.effective_chat.id, calls_msg)

    if opt_type != "call":
        await send_message_in_chunks(update.effective_chat.id, puts_msg)


    

# ---- IV surface fit (local) ----
def _fit_iv_surface_for_expiry(
        base: str,
        expiry_ts: int,
        spot: float,
        T: float,
        r: float,
        bm: dict,
        instruments: list,
        moneyness_band: float = 0.25,
        min_pts: int = 6
    ) -> tuple[float | None, int, dict]:  # todo: document on gdoc
    """
    Fit a quadratic polynomial to the IV surface for the given expiry timestamp (ms).
    Only strikes within [S*(1-band), S*(1+band)].
    Returns (iv_at_strike, chain_len, info_dict) where:
      iv_at_strike: fitted IV at K=spot, or None if fit failed
      chain_len: number of points used in the fit
      info_dict: {"fit": (c2,c1,c0) or None, "reason": str}
    """
    rows = []
    for inst in instruments:
        if int(inst.get("expiration_timestamp", 0)) != int(expiry_ts):
            continue
        K = float(inst.get("strike") or 0.0)
        if K <= 0:
            continue
        if not (spot * (1 - moneyness_band) <= K <= spot * (1 + moneyness_band)):
            continue
        summ = bm.get(inst["instrument_name"], {})
        bid = summ.get("bid_price"); ask = summ.get("ask_price")
        last = summ.get("last_price"); mark = summ.get("mark_price")
        last_ts = None
        if not (bid and ask and bid > 0 and ask > 0):
            last = None  # skip LAST if we can't prove freshness per strike
        mid = _pick_price_mid_last_mark(bid, ask, last, last_ts, mark)
        und = float(summ.get("underlying_price") or spot)
        quote = inst.get("quote_currency", "")
        usd_mid = mid if quote in ["USD", "USDC"] else (mid * und if mid and und else 0.0)
        if not usd_mid or usd_mid <= 0:
            continue
        opt_type = "call" if inst.get("option_type") == "call" else "put"
        iv = implied_vol(usd_mid, spot, K, T, r, opt_type)
        if iv and 0.0001 <= iv <= 5.0:
            rows.append((K, iv))

    chain_len = len(rows)
    if chain_len < min_pts:
        return None, chain_len, {"fit": None, "reason": "insufficient_points"}

    xs = np.array([math.log(K / spot) for (K, _iv) in rows], dtype=float)
    ys = np.array([_iv for (_K, _iv) in rows], dtype=float)
    try:
        c2, c1, c0 = np.polyfit(xs, ys, 2)
        iv_at_strike = float(c0)  # x=0 at K=S
        return max(1e-4, min(iv_at_strike, 5.0)), chain_len, {"fit": (c2, c1, c0), "reason": "ok"}
    except Exception:
        return None, chain_len, {"fit": None, "reason": "polyfit_failed"}

# ---- Monte Carlo ITM probability ----
def _mc_itm_prob(
        S: float,
        K: float,
        T: float,
        r: float,
        sigma: float,
        option_type: str,
        n_paths: int = 20000,
        antithetic: bool = True
    ) -> float | None:  # todo: document on gdoc
    """
    Monte Carlo simulation to estimate probability of expiring in-the-money.
        S: underlying price
        K: strike price
        T: time to expiration in years
        r: risk-free rate (annualized, decimal)
        sigma: volatility (annualized, decimal)
        option_type: "call" or "put"
        n_paths: number of MC paths (default 20000)
        antithetic: whether to use antithetic variates (default True)
    Returns probability as float in [0,1], or None if error.
    """
    if sigma is None or sigma <= 0 or T <= 0 or S <= 0 or K <= 0:
        return None
    try:
        n = n_paths // 2 if antithetic else n_paths
        z = np.random.standard_normal(n)
        drift = (r - 0.5 * sigma * sigma) * T
        diff = sigma * math.sqrt(T)
        ST1 = S * np.exp(drift + diff * z)
        if antithetic:
            ST2 = S * np.exp(drift - diff * z)
            ST = np.concatenate([ST1, ST2], axis=0)
        else:
            ST = ST1
        if option_type == "call":
            return float(np.mean(ST > K))
        else:
            return float(np.mean(ST < K))
    except Exception:
        return None

# === /prob (BS + local Surf + MC) ===
async def prob_itm_all(
        instrument_name: str,
        cache: dict
    ) -> tuple[dict | None, str | None]:
    """
    Compute ITM probabilities using:
      - Black–Scholes (using market-implied vol)
      - Local IV surface fit (quadratic polynomial)
      - Monte Carlo simulation (using surface or market vol)
    Combine them into an ensemble probability.
    Returns (result_dict, error_message) where result_dict has keys:
        inputs: {S, K, T_years, type, r, iv, realized_vol, mu_mc}
        probs: {bs, surface, mc, ensemble}
        weights: {bs, surface, mc, mc_floor}
        meta: {surface_chain_len, surface_fit, surface_reason}
    or (None, error_message) if error.
    """
    inst = await get_instrument(instrument_name)
    if not inst:
        return None, "Invalid or unknown option instrument."
    tkr = await get_ticker(instrument_name)
    if not tkr:
        return None, "Missing ticker."

    S = float(tkr.get("underlying_price") or 0.0)
    if S <= 0:
        return None, "Missing underlying price."
    K = float(inst.get("strike") or 0.0)
    option_type = "call" if inst.get("option_type") == "call" else "put"
    exp_ts = int(inst.get("expiration_timestamp") or 0)
    T = max((datetime.fromtimestamp(exp_ts/1000, tz=timezone.utc) - datetime.now(timezone.utc)).days/365, 1e-6)
    base = instrument_name.split("-")[0].upper()

    _arr, bm = await get_book_summary_by_currency(base, "option", ttl=8)
    usd_mid = await _usd_option_mid(inst, tkr, bm.get(instrument_name, {}), S)
    if usd_mid <= 0:
        return None, "Option price unavailable."

    r = await get_risk_free_rate(cache=_RFR_CACHE)
    iv_mkt = implied_vol(usd_mid, S, K, T, r, option_type)
    p_bs = bs_itm_probability(S, K, T, iv_mkt, option_type, r=r, q=0.0) if iv_mkt else None

    instruments = await get_option_instruments_cached(base, cache=cache)
    iv_surf, chain_len, surf_meta = _fit_iv_surface_for_expiry(
        base=base, expiry_ts=exp_ts, spot=S, T=T, r=r, bm=bm, instruments=instruments,
        moneyness_band=0.25, min_pts=6
    )
    p_surf = bs_itm_probability(S, K, T, iv_surf, option_type, r=r, q=0.0) if iv_surf else None

    sigma_for_mc = iv_surf or iv_mkt
    p_mc = _mc_itm_prob(S, K, T, r, sigma_for_mc, option_type, n_paths=20000, antithetic=True)

    w_bs = 0.6
    w_surf = 0.25 if (p_surf is not None and chain_len >= 10) else (0.15 if p_surf is not None else 0.0)
    w_mc = 0.15 if p_mc is not None else 0.0

    weights = [w for w, p in [(w_bs, p_bs), (w_surf, p_surf), (w_mc, p_mc)] if p is not None]
    if not weights:
        return None, "All probability engines failed."
    total = sum(weights)
    w_bs = (w_bs / total) if p_bs is not None else 0.0
    w_surf = (w_surf / total) if p_surf is not None else 0.0
    w_mc = (w_mc / total) if p_mc is not None else 0.0

    p_ensemble = 0.0
    if p_bs is not None:
        p_ensemble += w_bs * p_bs
    if p_surf is not None:
        p_ensemble += w_surf * p_surf
    if p_mc is not None:
        p_ensemble += w_mc * p_mc

    out = {
        "inputs": {"S": S, "K": K, "T_years": T, "type": option_type, "r": r, "iv": iv_mkt, "realized_vol": None, "mu_mc": None},
        "probs": {"bs": p_bs, "surface": p_surf, "mc": p_mc, "ensemble": p_ensemble},
        "weights": {"bs": round(w_bs, 4), "surface": round(w_surf, 4), "mc": round(w_mc, 4), "mc_floor": 0.0},
        "meta": {"surface_chain_len": chain_len, "surface_fit": surf_meta.get("fit"), "surface_reason": surf_meta.get("reason")}
    }
    return out, None

# async def prob(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
#     """
#     /prob [INSTRUMENT_NAME] - Compute ITM probability using BS + local Surf + MC
#     Example: /prob BTC-31DEC25-60000-C
#     """
#     if len(context.args) < 1:
#         await update.message.reply_text("Usage: /prob BTC-31DEC25-60000-C")
#         return
#     instrument_name = context.args[0].upper()
#     try:
#         res, err = await prob_itm_all(instrument_name)
#         if err:
#             await update.message.reply_text(err)
#             return
#         S = res["inputs"]["S"]; K = res["inputs"]["K"]; T = res["inputs"]["T_years"]
#         typ = res["inputs"]["type"]; r  = res["inputs"]["r"]
#         iv = res["inputs"]["iv"]
#         pbs = res["probs"]["bs"]; psurf = res["probs"]["surface"]; pmc = res["probs"]["mc"]; pen = res["probs"]["ensemble"]
#         w_bs = res["weights"]["bs"]; w_surf = res["weights"]["surface"]; w_mc = res["weights"]["mc"]

#         lines = [
#             _kv("Spot S (USD)",  fnum(S)),
#             _kv("Strike K",      fnum(K)),
#             _kv("Type",          typ.upper(), vw=12),
#             _kv("T (years)",     f"{T:.4f}"),
#             _kv("Risk-free r",   pct(r)),
#             _kv("Market IV",     "n/a" if iv is None else pct(iv)),
#             "",
#             _kv("BS (IV)",             pct(pbs)),
#             _kv("Surf (local fit)",    pct(psurf) if psurf is not None else "n/a"),
#             _kv("MC (GBM)",            pct(pmc) if pmc is not None else "n/a"),
#             "-" * 50,
#             _kv("Ensemble",      pct(pen)),
#             _kv("Weights",       "", lw=18, vw=12),
#             _kv("  BS",          f"{w_bs:.2f}", lw=18, vw=12),
#             _kv("  Surf",        f"{w_surf:.2f}", lw=18, vw=12),
#             _kv("  MC",          f"{w_mc:.2f}", lw=18, vw=12),
#         ]
#         msg = f"*{instrument_name} — ITM Probability*\n" + "```\n" + "\n".join(lines) + "\n```"
#         await update.message.reply_text(msg, parse_mode="Markdown")
#     except Exception as e:
#         logging.exception(e)
#         await update.message.reply_text("Error computing ITM probability.")

async def prob(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /prob [INSTRUMENT_NAME] - Compute ITM probability using BS + local Surf + MC
    Example: /prob BTC-31DEC25-60000-C
    """
    if len(context.args) < 1:
        await update.message.reply_text("Usage: /prob BTC-31DEC25-60000-C")
        return
    instrument_name = context.args[0].upper()
    try:
        _, _, msg, is_error = await get_prob(instrument_name)
        await update.message.reply_text(msg, parse_mode="Markdown")
    except Exception as e:
        logging.exception(f"Error in deribit prob: {e}")
        await update.message.reply_text("Error computing ITM probability.")

async def get_prob(inst_name: str) -> tuple[dict, dict, str, bool]:
    """
    /prob [INSTRUMENT_NAME] - Compute ITM probability using BS + local Surf + MC
    Example: /prob BTC-31DEC25-60000-C
    """
    try:
        res, err = await prob_itm_all(inst_name, _OPT_CACHE)
        if err:
            logging.warning(f"Error in deribit get_prob: {err}")
            return {}, {}, err, True
        S = res["inputs"]["S"]; K = res["inputs"]["K"]; T = res["inputs"]["T_years"]
        typ = res["inputs"]["type"]; r  = res["inputs"]["r"]
        iv = res["inputs"]["iv"]
        pbs = res["probs"]["bs"]; psurf = res["probs"]["surface"]; pmc = res["probs"]["mc"]; pen = res["probs"]["ensemble"]
        w_bs = res["weights"]["bs"]; w_surf = res["weights"]["surface"]; w_mc = res["weights"]["mc"]

        raw = {
            PRETTY_PARAMETERS.SPOT_PRICE.value: S,
            PRETTY_PARAMETERS.STRIKE_PRICE.value: K,
            PRETTY_PARAMETERS.OPTION_TYPE.value: typ.upper(),
            PRETTY_PARAMETERS.YEARS_TO_EXPIRY.value: round(T, 4),
            PRETTY_PARAMETERS.INTEREST_RATE.value: r,
            PRETTY_PARAMETERS.IMPLIED_VOLATILITY.value: iv,
            PRETTY_PARAMETERS.BS_IMPLIED_VOLATILITY.value: pbs,
            PRETTY_PARAMETERS.LOCAL_SURFACE_IV_FIT.value: psurf,
            "MC (GBM)": pmc,
            "Ensemble": pen,
            "BS weight": round(w_bs, 2),
            "Surf Weight": round(w_surf, 2),
            "MC Weight": round(w_mc, 2)
        }
        processed = {
            PRETTY_PARAMETERS.SPOT_PRICE.value: fnum(S),
            PRETTY_PARAMETERS.STRIKE_PRICE.value: fnum(K),
            PRETTY_PARAMETERS.OPTION_TYPE.value: typ.upper(),
            PRETTY_PARAMETERS.YEARS_TO_EXPIRY.value: round(T, 4),
            PRETTY_PARAMETERS.INTEREST_RATE.value: pct(r),
            PRETTY_PARAMETERS.IMPLIED_VOLATILITY.value: "n/a" if iv is None else pct(iv),
            PRETTY_PARAMETERS.BS_IMPLIED_VOLATILITY.value: pct(pbs),
            PRETTY_PARAMETERS.LOCAL_SURFACE_IV_FIT.value: pct(psurf) if psurf is not None else "n/a",
            "MC (GBM)": pct(pmc) if pmc is not None else "n/a",
            "Ensemble": pct(pen),
            "BS weight": round(w_bs, 2),
            "Surf Weight": round(w_surf, 2),
            "MC Weight": round(w_mc, 2)
        }
        lines = [
            _kv("Spot S (USD)",  fnum(S)),
            _kv("Strike K",      fnum(K)),
            _kv("Type",          typ.upper(), vw=12),
            _kv("T (years)",     f"{T:.4f}"),
            _kv("Risk-free r",   pct(r)),
            _kv("Market IV",     "n/a" if iv is None else pct(iv)),
            "",
            _kv("BS (IV)",             pct(pbs)),
            _kv("Surf (local fit)",    pct(psurf) if psurf is not None else "n/a"),
            _kv("MC (GBM)",            pct(pmc) if pmc is not None else "n/a"),
            "-" * 50,
            _kv("Ensemble",      pct(pen)),
            _kv("Weights",       "", lw=18, vw=12),
            _kv("  BS",          f"{w_bs:.2f}", lw=18, vw=12),
            _kv("  Surf",        f"{w_surf:.2f}", lw=18, vw=12),
            _kv("  MC",          f"{w_mc:.2f}", lw=18, vw=12),
        ]
        msg = f"*{inst_name} — ITM Probability*\n" + "```\n" + "\n".join(lines) + "\n```"
        return raw, processed, msg, False
    except Exception as e:
        logging.exception(f"Error in deribit get_prob: {e}")
        return {}, {}, "Error computing ITM probability.", True

# === /misprice ===
# === /misprice [BTC|ETH] [Nexp=3] [model=har|garch] [band=0.30] ===
async def misprice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Flags mispriced options by VRP z-score:
      VRP = IV_annualized - RV_forecast_annualized
    Steps:
      1) Deribit IV surface (bid/ask mid) for next N expiries within a moneyness band
      2) Realized vol series (YZ per-day) -> RV forecast via HAR (default) or GARCH
      3) Cross-sectional z-score of VRP within each expiry
    """
    base = "BTC"; n_exp = 3; model = "har"; band = 0.30; topn = 3
    # Parse args
    if context.args:
        a0 = context.args[0].upper()
        if a0 in ("BTC","ETH"):
            base = a0
            if len(context.args) >= 2:
                try: n_exp = max(1, min(6, int(context.args[1])))
                except: pass
            if len(context.args) >= 3:
                m = context.args[2].lower()
                if m in ("har","garch"): model = m
            if len(context.args) >= 4:
                try: band = max(0.10, min(0.50, float(context.args[3])))
                except: pass
        else:
            try: n_exp = max(1, min(6, int(context.args[0]))); 
            except: pass

    # Spot & data
    S = await _get_deribit_index_usd_first(base, cache=_INDEX_CACHE)
    if S is None:
        await update.message.reply_text(f"Could not fetch {base} index price.")
        return
    S = float(S)
    r = await get_risk_free_rate(cache=_RFR_CACHE)
    _arr, bm = await get_book_summary_by_currency(base, "option", ttl=8)
    instruments = await get_option_instruments_cached(base, cache=_OPT_CACHE)
    inst_map = {x["instrument_name"]: x for x in instruments}

    # RV forecast (annualized)
    rv_for = await _forecast_rv_annualized(base, model=model)
    if rv_for is None:
        await update.message.reply_text("Could not compute RV forecast (HAR/GARCH).")
        return

    expiries = await _unique_live_expiries(base, limit=n_exp)
    if not expiries:
        await update.message.reply_text(f"No live expiries for {base}.")
        return

    out_lines = [f"*{base} — Mispricing by VRP z-score*",
                 f"_Model_: {model.upper()} | _Spot_: {S:,.2f} USD | _RV forecast_: {rv_for*100:.2f}%\n```",
                 f"{'Expiry':<9} {'DTE':>3} {'#pts':>4} {'IV̄':>7} {'Overpriced →':>30} {'← Underpriced':>30}"]

    now = datetime.now(timezone.utc)

    for exp_ts in expiries:
        rows = _build_iv_surface_for_expiry(base, exp_ts, S, r, band, bm, inst_map)
        if not rows:
            continue
        # VRP per option (vol difference, annualized)
        vrps = [row["iv"] - rv_for for row in rows]
        z = _zscore_list(vrps)
        for i, row in enumerate(rows):
            row["vrp"] = vrps[i]
            row["z"] = z[i]

        # rank
        rows.sort(key=lambda x: x["z"], reverse=True)
        top_over = rows[:topn]
        rows.sort(key=lambda x: x["z"])
        top_under = rows[:topn]

        # expiry header line
        exp_dt = datetime.fromtimestamp(exp_ts/1000, tz=timezone.utc)
        dte = max(1, (exp_dt - now).days)
        iv_mean = float(np.mean([r["iv"] for r in rows]))
        # Simple compact summary strings (inst name trimmed)
        def _side_fmt(rr):
            name = rr["name"]
            short = (name[:18] + "…") if len(name) > 19 else name
            return f"{short}:{rr['type'][0].upper()} K={rr['K']:.0f} IV={rr['iv']*100:5.2f}% z={rr['z']:+4.2f}"
        over_s = " | ".join(_side_fmt(x) for x in top_over)
        under_s = " | ".join(_side_fmt(x) for x in top_under)

        out_lines.append(f"{exp_dt.strftime('%d%b%y').upper():<9} {dte:>3} {len(rows):>4} {iv_mean*100:>6.2f}%  {over_s:>30}  {under_s:>30}")

    out_lines.append("```")
    await update.message.reply_text("\n".join(out_lines), parse_mode="MarkdownV2")

# === GLOBAL ERROR HANDLER ===
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logging.error("Exception while handling an update:", exc_info=context.error)
    try:
        if isinstance(update, Update) and update.effective_message:
            await update.effective_message.reply_text("Sorry, something went wrong while processing that command.")
    except Exception:
        pass

# === START MESSAGE ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    /start - Show welcome message and available commands
    """
    chat_id = update.effective_chat.id
    text = (
        "Welcome to the <b>Deribit Market Bot</b>.\n\n"
        "<b>Commands:</b>\n"
        "/price <code>BTC</code> – Spot Snapshot (broken)\n"
        "/basis <code>BTC</code> – Futures v Spot (broken)\n"
        "/option <code>BTC-31DEC25-60000-C</code> – Mkt v Rls Vols\n"
        "/greeks <code>BTC-31DEC25-60000-C</code> – Option Greeks\n"
        "/runsc [BTC|ETH] – Sell Call run (ATM by expiry)\n"
        "/runsp [BTC|ETH] – Sell Put run (ATM by expiry)\n"
        "/runbc [BTC|ETH] – Buy Call run (ATM by expiry)\n"
        "/runbp [BTC|ETH] – Buy Put run (ATM by expiry)\n"
        "/allruns [BTC|ETH] - All runs (ATM by expiry)\n"
        "/allrunsexp [BTC|ETH] [C|P] [T|F] - All runs for all expiries (Fridays only by default)\n"
        "/prob  <code>BTC-31DEC25-60000-C</code> – ITM Probability\n"
        "/misprice [BTC|ETH] [Nexp] [har|garch] [band] – IV surface vs RV forecast; flags top mispricings by VRP z‑score\n"

    )
    await update.message.reply_text(text, parse_mode="HTML")
    print(f"chat_id: {chat_id}")  # todo: remove when done
    return chat_id

# === /price BTC or ETH ===
# async def price(update: Update, context: ContextTypes.DEFAULT_TYPE, appBase: str = None) -> list[str]:
#     """
#     /price [BTC|ETH] - Show spot, future quotes, 24h stats
#     """
#     base = "BTC"
#     if not appBase and context.args:
#         base = context.args[0].upper()
#     else:
#         base = appBase.upper()

#     # Spot (Index) — prefer USD, fall back to USDT
#     idx_usd = await get_index_price(f"{base.lower()}_usd", cache=_INDEX_CACHE)
#     idx_usdt = await get_index_price(f"{base.lower()}_usdt", cache=_INDEX_CACHE)
#     if idx_usd is not None:
#         spot = float(idx_usd)
#         idx_label = f"{base}USD"
#     elif idx_usdt is not None:
#         spot = float(idx_usdt)
#         idx_label = f"{base}USDT"
#     else:
#         await update.message.reply_text(f"Could not fetch spot for {base}.")
#         return

#     # Pick a future to show quotes/stats: prefer PERPETUAL with max OI
#     futs = get_futures_instruments(base)
#     _, bm_fut = await get_book_summary_by_currency(base, "future", ttl=5)

#     def _oi_of(name: str) -> int:
#         return int((bm_fut.get(name, {}) or {}).get("open_interest", 0) or 0)

#     perp = [f for f in futs if "PERPETUAL" in (f.get("instrument_name") or "").upper()]
#     if perp:
#         inst_name = max(perp, key=lambda f: _oi_of(f["instrument_name"]))["instrument_name"]
#     else:
#         # fall back to the most active future by OI
#         if not futs:
#             await update.message.reply_text(f"No futures found for {base}.")
#             return
#         inst_name = max(futs, key=lambda f: _oi_of(f["instrument_name"]))["instrument_name"]

#     summ = bm_fut.get(inst_name, {})
#     tkr = await get_ticker(inst_name) or {}

#     # Compose prices with hierarchy mid -> last (fresh) -> mark
#     bid = tkr.get("best_bid_price") or summ.get("bid_price")
#     ask = tkr.get("best_ask_price") or summ.get("ask_price")
#     last = tkr.get("last_price") or summ.get("last_price")
#     mark = tkr.get("mark_price") or summ.get("mark_price")
#     last_ts = None
#     if (not bid or bid <= 0 or not ask or ask <= 0) and last and last > 0:
#         last_ts = await _get_last_trade_ts_ms(inst_name)
#     mid = _pick_price_mid_last_mark(bid, ask, last, last_ts, mark)

#     # 24h stats from ticker
#     stats = (tkr.get("stats") or {})
#     chg_pct = stats.get("price_change", None)
#     high_24h = stats.get("high", None)
#     low_24h = stats.get("low", None)
#     vol_24h = stats.get("volume", None)  # base-coin volume if provided
#     vol_delta = stats.get("volume_change") or stats.get("volume_change_pct")  # may be missing

#     def fnum(x, n=2):
#         try:
#             return f"{float(x):,.{n}f}"
#         except Exception:
#             return "n/a"

#     def fpct(p):
#         if p is None:
#             return "n/a"
#         try:
#             return f"{float(p):.2f}%"
#         except Exception:
#             return "n/a"

#     header = f"*{idx_label} — Deribit Market Snapshot*"
#     lines = [
#         "```",
#         _kv("Index (Spot)", fnum(spot)),
#         _kv("Mark Price",   fnum(mark)),
#         _kv("Mid Price",    fnum(mid)),
#         _kv("Bid",          fnum(bid)),
#         _kv("Ask",          fnum(ask)),
#         _kv("24h Change",   fpct(chg_pct)),
#         _kv("24h High",     fnum(high_24h)),
#         _kv("24h Low",      fnum(low_24h)),
#         _kv("24h Volume (BTC)", fnum(vol_24h, 2) if vol_24h is not None else "n/a"),
#         _kv("Volume Δ 1D",  fpct(vol_delta) if vol_delta is not None else "n/a"),
#         "```",
#     ]
#     await update.message.reply_text(header + "\n" + "\n".join(lines), parse_mode="Markdown")
#     return [header] + lines[1:-1]
async def price(update: Update, context: ContextTypes.DEFAULT_TYPE) -> list[str]:
    """
    /price [BTC|ETH] - Show spot, future quotes, 24h stats

    price
        get_price
            get_index_price(usd)/get_index_price(usdt)
                try _cget(_INDEX_CACHE), if exists, return, else
                try pulling from api, if not none, then _cset(_INDEX_CACHE) before return
            get_futures_instruments
                try pulling from api for list of future instruments
            get_book_summary_by_currency
                try _cget(_BOOK_CACHE), if exists, return, else 
                try pulling from api then _cset(_BOOK_CACHE)
                return
            get_ticker
                try pull from api before return
            _get_last_trade_ts_ms
                try pulling from api and return last trade's timestamp
            _pick_price_mid_last_mark
                no api calls or cache calls; pure calculations
    """
    
    base = "BTC"
    if context.args:
        base = context.args[0].upper()

    lines, msg, is_error = await get_price(base)
    if is_error:
        await update.message.reply_text(msg)
        return
    
    await update.message.reply_text(msg, parse_mode="Markdown")

async def get_price(base: str) -> tuple[list[str], str, bool]:
    """
    /price [BTC|ETH] - Show spot, future quotes, 24h stats

    get_price
        get_index_price(usd)/get_index_price(usdt)
            try _cget(_INDEX_CACHE), if exists, return, else
            try pulling from api, if not none, then _cset(_INDEX_CACHE) before return
        get_futures_instruments
            try pulling from api for list of future instruments
        get_book_summary_by_currency
            try _cget(_BOOK_CACHE), if exists, return, else 
            try pulling from api then _cset(_BOOK_CACHE)
            return
        get_ticker
            try pull from api before return
        _get_last_trade_ts_ms
            try pulling from api and return last trade's timestamp
        _pick_price_mid_last_mark
            no api calls or cache calls; pure calculations
    """
    # Spot (Index) — prefer USD, fall back to USDT
    idx_usd = await get_index_price(f"{base.lower()}_usd", cache=_INDEX_CACHE)
    idx_usdt = await get_index_price(f"{base.lower()}_usdt", cache=_INDEX_CACHE)
    if idx_usd is not None:
        spot = float(idx_usd)
        idx_label = f"{base}USD"
    elif idx_usdt is not None:
        spot = float(idx_usdt)
        idx_label = f"{base}USDT"
    else:
        return "", f"Could not fetch spot for {base}.", True

    # Pick a future to show quotes/stats: prefer PERPETUAL with max OI
    futs = get_futures_instruments(base)
    _, bm_fut = await get_book_summary_by_currency(base, "future", ttl=5)

    def _oi_of(name: str) -> int:
        return int((bm_fut.get(name, {}) or {}).get("open_interest", 0) or 0)

    perp = [f for f in futs if "PERPETUAL" in (f.get("instrument_name") or "").upper()]
    if perp:
        inst_name = max(perp, key=lambda f: _oi_of(f["instrument_name"]))["instrument_name"]
    else:
        # fall back to the most active future by OI
        if not futs:
            return "", f"No futures found for {base}.", True
        inst_name = max(futs, key=lambda f: _oi_of(f["instrument_name"]))["instrument_name"]

    summ = bm_fut.get(inst_name, {})
    tkr = await get_ticker(inst_name) or {}

    # Compose prices with hierarchy mid -> last (fresh) -> mark
    bid = tkr.get("best_bid_price") or summ.get("bid_price")
    ask = tkr.get("best_ask_price") or summ.get("ask_price")
    last = tkr.get("last_price") or summ.get("last_price")
    mark = tkr.get("mark_price") or summ.get("mark_price")
    last_ts = None
    if (not bid or bid <= 0 or not ask or ask <= 0) and last and last > 0:
        last_ts = await _get_last_trade_ts_ms(inst_name)
    mid = _pick_price_mid_last_mark(bid, ask, last, last_ts, mark)

    # 24h stats from ticker
    stats = (tkr.get("stats") or {})
    chg_pct = stats.get("price_change", None)
    high_24h = stats.get("high", None)
    low_24h = stats.get("low", None)
    vol_24h = stats.get("volume", None)  # base-coin volume if provided
    vol_delta = stats.get("volume_change") or stats.get("volume_change_pct")  # may be missing

    header = f"*{idx_label} — Deribit Market Snapshot*"
    lines = [
        fnum(spot),
        fnum(mark),
        fnum(mid),
        fnum(bid),
        fnum(ask),
        fpct(chg_pct),
        fnum(high_24h),
        fnum(low_24h),
        fnum(vol_24h, 2) if vol_24h is not None else "n/a",
        fpct(vol_delta) if vol_delta is not None else "n/a",
    ]
    tele_lines = [
        "```",
        _kv("Index (Spot)", fnum(spot)),
        _kv("Mark Price",   fnum(mark)),
        _kv("Mid Price",    fnum(mid)),
        _kv("Bid",          fnum(bid)),
        _kv("Ask",          fnum(ask)),
        _kv("24h Change",   fpct(chg_pct)),
        _kv("24h High",     fnum(high_24h)),
        _kv("24h Low",      fnum(low_24h)),
        _kv("24h Volume (BTC)", fnum(vol_24h, 2) if vol_24h is not None else "n/a"),
        _kv("Volume Δ 1D",  fpct(vol_delta) if vol_delta is not None else "n/a"),
        "```",
    ]

    return [idx_label] + lines, header + "\n" + "\n".join(tele_lines), False

# === /basis BTC or ETH ===
async def basis(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:  # todo: yet to incorporate
    """
    /basis [BTC|ETH] - Show futures basis table vs spot
    """
    base = "BTC"
    if context.args:
        base = context.args[0].upper()

    spot, spot_src = await get_spot_reference(base)
    if spot is None:
        await update.message.reply_text(f"Could not fetch spot for {base}.")
        return

    futs = [f for f in get_futures_instruments(base)
            if "PERPETUAL" not in (f.get("instrument_name") or "").upper()]
    if not futs:
        await update.message.reply_text(f"No dated futures found for {base}.")
        return

    _, bm = await get_book_summary_by_currency(base, "future", ttl=5)
    now = datetime.now(timezone.utc)

    rows = []
    for f in futs:
        nm = f["instrument_name"]
        exp_dt = datetime.fromtimestamp(f["expiration_timestamp"] / 1000, tz=timezone.utc)
        dte = max(1, (exp_dt - now).days)

        summ = bm.get(nm, {}) or {}
        bid = summ.get("bid_price"); ask = summ.get("ask_price")
        last = summ.get("last_price"); mark = summ.get("mark_price")

        last_ts = None
        if (not bid or bid <= 0 or not ask or ask <= 0) and last and last > 0:
            last_ts = await _get_last_trade_ts_ms(nm)

        mid = _pick_price_mid_last_mark(bid, ask, last, last_ts, mark)
        if not mid:
            # fallback: pull from ticker as well
            tkr = await get_ticker(nm) or {}
            bid = tkr.get("best_bid_price"); ask = tkr.get("best_ask_price")
            last = tkr.get("last_price");     mark = tkr.get("mark_price")
            last_ts = None
            if (not bid or bid <= 0 or not ask or ask <= 0) and last and last > 0:
                last_ts = await _get_last_trade_ts_ms(nm)
            mid = _pick_price_mid_last_mark(bid, ask, last, last_ts, mark)

        if not mid:
            continue

        basis_abs = float(mid) - float(spot)                 # futures - spot
        pct = (basis_abs / float(spot)) * 100.0              # % gain of basis
        ann = pct * (365.0 / dte)                            # annualised yield (simple)

        rows.append((nm, basis_abs, pct, ann, dte))

    rows.sort(key=lambda x: x[4])  # by tenor (days)

    def fnum(x, n=2): return f"{float(x):,.{n}f}"

    header = f"*{base} Basis*\nSpot ({spot_src}): {fnum(spot)}\n"
    body = (
        "```\n"
        f"{'Contract':<13} {'Basis':>8} {'%':>6} {'Ann%':>6} {'Dte':>3}\n"
        f"{'─'*13} {'─'*8:>8} {'─'*6:>6} {'─'*6:>6} {'─'*3:>3}\n"
    )
    for nm, babs, pct, ann, dte in rows:
        body += f"{nm:<13} {fnum(babs,2):>8} {pct:>5.2f}% {ann:>5.2f}% {dte:>3}\n"
    body += "```"

    await update.message.reply_text(header + body, parse_mode="Markdown")

# === /option BTC-31DEC25-60000-C ===
# async def option(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
#     """
#     /option [INSTRUMENT_NAME] - Option valuation vs realized vol
#     Example: /option BTC-31DEC25-60000-C
#     """
#     if not context.args:
#         await update.message.reply_text("Usage: /option BTC-31DEC25-60000-C")
#         return

#     inst_name = context.args[0].upper()
#     try:
#         inst = await get_instrument(inst_name)
#         if not inst:
#             await update.message.reply_text("Invalid or unknown option instrument.")
#             return

#         base = inst_name.split("-")[0].upper()
#         quote_ccy = (inst.get("quote_currency") or "").upper()

#         # Inverse-only guard (coin-settled BTC/ETH options)
#         if quote_ccy not in ("BTC", "ETH"):
#             await update.message.reply_text(
#                 "This looks like a USD/USDC‑settled option. "
#                 "This command supports only inverse coin‑settled options (BTC/ETH)."
#             )
#             return

#         # Deribit index spot (USD-first)
#         S = await _get_deribit_index_usd_first(base, cache=_INDEX_CACHE)
#         if S is None:
#             await update.message.reply_text(f"Could not fetch {base} index price.")
#             return
#         S = float(S)

#         # Expiry / tenor
#         expiry_ts = int(inst.get("expiration_timestamp") or 0)
#         now = datetime.now(timezone.utc)
#         expiry_dt = datetime.fromtimestamp(expiry_ts / 1000, tz=timezone.utc)
#         T_years = max((expiry_dt - now).total_seconds() / (365.0 * 24.0 * 3600.0), 1e-6)
#         dte_days = (expiry_dt - now).total_seconds() / 86400.0
#         K = float(inst.get("strike") or 0.0)
#         opt_type = "call" if inst.get("option_type") == "call" else "put"

#         # Mid (coin) from bid/ask only (no LAST, no MARK)
#         _, bm = await get_book_summary_by_currency(base, "option", ttl=8)
#         summ = bm.get(inst_name, {}) or {}
#         bid = float(summ.get("bid_price") or 0.0)
#         ask = float(summ.get("ask_price") or 0.0)
#         if not (bid > 0 and ask > 0):
#             await update.message.reply_text("No live bid/ask — cannot compute coin mid for this option.")
#             return
#         coin_mid = (bid + ask) / 2.0

#         # USD conversion via index spot
#         usd_mid = coin_mid * S

#         # RFR and Market IV (from BS)
#         r = await get_risk_free_rate(cache=_RFR_CACHE)
#         iv = implied_vol(usd_mid, S, K, T_years, r, opt_type)

#         # Realized vol (Yang–Zhang, adaptive by DTE)
#         rv = get_realized_vol_yz_dynamic(base, dte_days)

#         # Fair price under RV and Diff
#         fair_price = bs_price(S, K, T_years, r, rv, opt_type)
#         diff = usd_mid - fair_price
#         status = "*Overpriced*" if diff > 0 else "*Underpriced*"

#         # Pretty print (same style as your screenshot)
#         coin_sym = base
#         def fnum(x, n=2): 
#             try: return f"{float(x):,.{n}f}"
#             except Exception: return "n/a"
#         def pct(x): 
#             try: return f"{float(x)*100:.2f}%"
#             except Exception: return "n/a"

#         msg = (
#             f"*{inst_name} — Option Valuation*\n"
#             "```\n"
#             f"{'Spot (USD)':<18}: {fnum(S):>12}\n"
#             f"{'Strike (USD)':<18}: {fnum(K):>12}\n"
#             f"{'Type':<18}: {opt_type.upper():>12}\n"
#             f"{'Expiry (days)':<18}: {dte_days:>12.1f}\n"
#             f"{'Risk‑Free r':<18}: {pct(r):>12}\n"
#             f"{('Option Mid (' + coin_sym + ')'):<18}: {coin_mid:>12,.6f}\n"
#             f"{'Option Mid (USD)':<18}: {usd_mid:>12,.2f}\n"
#             f"{'Fair Price (USD)':<18}: {fair_price:>12,.2f}\n"
#             f"{'Diff (USD)':<18}: {diff:>12,.2f}\n"
#             f"{'Market IV':<18}: {pct(iv):>12}\n"
#             f"{'Realized Vol (YZ)':<18}: {pct(rv):>12}\n"
#                         "```\n"
#             f"{status}"
#         )
#         await update.message.reply_text(msg, parse_mode="Markdown")
#     except Exception as e:
#         logging.exception(e)
#         await update.message.reply_text("Error analyzing option.")

async def option(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /option [INSTRUMENT_NAME] - Option valuation vs realized vol
    Example: /option BTC-31DEC25-60000-C
    """
    if not context.args:
        await update.message.reply_text("Usage: /option BTC-31DEC25-60000-C")
        return

    inst_name = context.args[0].upper()
    try:
        _, _, msg, is_error = await get_option(inst_name)
        if is_error:
            await update.message.reply_text(msg)
            return
        await update.message.reply_text(msg, parse_mode="Markdown")
    except Exception as e:
        logging.exception(e)
        await update.message.reply_text("Error analyzing option.")

async def get_option(inst_name: str) -> tuple[dict, dict, str, bool]:
    """
    /option [INSTRUMENT_NAME] - Option valuation vs realized vol
    Example: /option BTC-31DEC25-60000-C
    Returns
        raw: dict of raw values if val else None (any type)
        processed: dict of processed vals in valid dp else 'n/a' (str type)
        msg: telegram message (str type)
        is_error: True/ False (bool type)
    """
    try:
        inst = await get_instrument(inst_name)
        if not inst:
            return {}, {}, "Invalid or unknown option instrument.", True

        base = inst_name.split("-")[0].upper()
        quote_ccy = inst.get("quote_currency", "").upper()

        # Inverse-only guard (coin-settled BTC/ETH options)
        if quote_ccy not in ("BTC", "ETH"):
            return {}, {}, "This looks like a USD/USDC-settled option.\n" \
                    "This command supports only inverse coin-settled options (BTC/ETH).", True

        # Deribit index spot (USD-first)
        S = await _get_deribit_index_usd_first(base, cache=_INDEX_CACHE)
        if S is None:
            return {}, {}, f"Could not fetch {base} index price.", True
        S = float(S)

        # Expiry / tenor
        expiry_ts = int(inst.get("expiration_timestamp") or 0)
        now = datetime.now(timezone.utc)
        expiry_dt = datetime.fromtimestamp(expiry_ts / 1000, tz=timezone.utc)
        T_years = max((expiry_dt - now).total_seconds() / (365.0 * 24.0 * 3600.0), 1e-6)
        dte_days = (expiry_dt - now).total_seconds() / 86400.0  # days
        K = float(inst.get("strike", 0.0))
        opt_type = "call" if inst.get("option_type") == "call" else "put"

        # Mid (coin) from bid/ask only (no LAST, no MARK)
        _, bm = await get_book_summary_by_currency(base, "option", ttl=8)
        summ = bm.get(inst_name, {})
        bid = float(summ.get("bid_price", 0.0))
        ask = float(summ.get("ask_price", 0.0))
        if not (bid > 0 and ask > 0):
            return {}, {}, "No live bid/ask — cannot compute coin mid for this option.", True
        coin_mid = (bid + ask) / 2.0

        # USD conversion via index spot
        usd_mid = coin_mid * S

        # RFR and Market IV (from BS)
        r = await get_risk_free_rate(cache=_RFR_CACHE)
        iv = implied_vol(usd_mid, S, K, T_years, r, opt_type)

        # Realized vol (Yang–Zhang, adaptive by DTE)
        rv = await get_realized_vol_yz_dynamic(base, dte_days)

        # Fair price under RV and Diff
        fair_price = bs_price(S, K, T_years, r, rv, opt_type)
        diff = usd_mid - fair_price
        status = "Overpriced" if diff > 0 else "Underpriced"

        # Pretty print (same style as your screenshot)
        coin_sym = base
        raw = {
            PRETTY_PARAMETERS.INSTRUMENT_NAME.value: inst_name,
            PRETTY_PARAMETERS.SPOT_PRICE.value: (round(S, 3) if S else None),
            PRETTY_PARAMETERS.STRIKE_PRICE.value: (round(K, 3) if K else None),
            PRETTY_PARAMETERS.OPTION_TYPE.value: opt_type.upper(),
            PRETTY_PARAMETERS.DAYS_TO_EXPIRY.value: (round(dte_days) if dte_days else None),
            PRETTY_PARAMETERS.INTEREST_RATE.value: (round(r*100, 2) if r else None),
            PRETTY_PARAMETERS.OPTION_MID.value+' (' + coin_sym + ')': (round(coin_mid, 6) if coin_mid else None),
            PRETTY_PARAMETERS.OPTION_MID.value+' (USD)': (round(usd_mid, 2) if usd_mid else None),
            PRETTY_PARAMETERS.FAIR_PRICE.value: (round(fair_price, 2) if fair_price else None),
            PRETTY_PARAMETERS.PRICE_DIFF.value: (round(diff, 2) if diff else None),
            PRETTY_PARAMETERS.IMPLIED_VOLATILITY.value: (round(iv*100, 2) if iv else None),
            PRETTY_PARAMETERS.REALIZED_VOLATILITY_YZ.value: (round(rv*100, 2) if rv else None),
            PRETTY_PARAMETERS.STATUS.value: status
        }
        processed = {
            PRETTY_PARAMETERS.INSTRUMENT_NAME.value: inst_name,
            PRETTY_PARAMETERS.SPOT_PRICE.value: fnum(S),
            PRETTY_PARAMETERS.STRIKE_PRICE.value: fnum(K),
            PRETTY_PARAMETERS.OPTION_TYPE.value: opt_type.upper(),
            PRETTY_PARAMETERS.DAYS_TO_EXPIRY.value: fnum(dte_days, 1),
            PRETTY_PARAMETERS.INTEREST_RATE.value: pct(r),
            PRETTY_PARAMETERS.OPTION_MID.value+' (' + coin_sym + ')': fnum(coin_mid, 6),
            PRETTY_PARAMETERS.OPTION_MID.value+' (USD)': fnum(usd_mid, 2),
            PRETTY_PARAMETERS.FAIR_PRICE.value: fnum(fair_price, 2),
            PRETTY_PARAMETERS.PRICE_DIFF.value: fnum(diff, 2),
            PRETTY_PARAMETERS.IMPLIED_VOLATILITY.value: pct(iv),
            PRETTY_PARAMETERS.REALIZED_VOLATILITY_YZ.value: pct(rv),
            PRETTY_PARAMETERS.STATUS.value: status
        }
        msg = (
            f"*{raw[PRETTY_PARAMETERS.INSTRUMENT_NAME.value]} — Option Valuation*\n"
            "```\n"
            f"{(PRETTY_PARAMETERS.SPOT_PRICE.value+' (USD)'):<18}: {raw[PRETTY_PARAMETERS.SPOT_PRICE.value]:>12}\n"
            f"{(PRETTY_PARAMETERS.STRIKE_PRICE.value+' (USD)'):<18}: {raw[PRETTY_PARAMETERS.STRIKE_PRICE.value]:>12}\n"
            f"{PRETTY_PARAMETERS.OPTION_TYPE.value:<18}: {raw[PRETTY_PARAMETERS.OPTION_TYPE.value]:>12}\n"
            f"{(PRETTY_PARAMETERS.DAYS_TO_EXPIRY.value+' (days)'):<18}: {raw[PRETTY_PARAMETERS.DAYS_TO_EXPIRY.value]:>12.1f}\n"
            f"{PRETTY_PARAMETERS.INTEREST_RATE.value:<18}: {raw[PRETTY_PARAMETERS.INTEREST_RATE.value]:>12}%\n"
            f"{(PRETTY_PARAMETERS.OPTION_MID.value+' (' + coin_sym + ')'):<18}: {raw[PRETTY_PARAMETERS.OPTION_MID.value+' (' + coin_sym + ')']:>12,.6f}\n"
            f"{(PRETTY_PARAMETERS.OPTION_MID.value+' (USD)'):<18}: {raw[PRETTY_PARAMETERS.OPTION_MID.value+' (USD)']:>12,.2f}\n"
            f"{(PRETTY_PARAMETERS.FAIR_PRICE.value+' (USD)'):<18}: {raw[PRETTY_PARAMETERS.FAIR_PRICE.value]:>12,.2f}\n"
            f"{PRETTY_PARAMETERS.PRICE_DIFF.value+' (USD)':<18}: {raw[PRETTY_PARAMETERS.PRICE_DIFF.value]:>12,.2f}\n"
            f"{PRETTY_PARAMETERS.IMPLIED_VOLATILITY.value:<18}: {raw[PRETTY_PARAMETERS.IMPLIED_VOLATILITY.value]:>12}%\n"
            f"{PRETTY_PARAMETERS.REALIZED_VOLATILITY_YZ.value:<18}: {raw[PRETTY_PARAMETERS.REALIZED_VOLATILITY_YZ.value]:>12}%\n"
             "```\n"
            f"{raw[PRETTY_PARAMETERS.STATUS.value]}"
        )
        return raw, processed, msg, False
    except Exception as e:
        logging.exception(e)
        return {}, "Error analyzing option.", True

# === /greeks BTC-31DEC25-60000-C ===
# async def greeks(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
#     """
#     /greeks [INSTRUMENT_NAME] - Show option Greeks (Delta, Gamma, Vega, Theta, Rho)
#     Example: /greeks BTC-31DEC25-6000-C
#     """
#     if not context.args:
#         await update.message.reply_text("Usage: /greeks BTC-31DEC25-60000-C")
#         return
#     inst = context.args[0].upper()
#     data, err = await bs_greeks_wrapper(inst, cache=_RFR_CACHE)
#     if err:
#         await update.message.reply_text(err)
#         print(err)
#         return
#     g_mkt = data["g_mkt"]
#     msg = (
#         f"*{inst} — Greeks (mid→last(fresh)→mark)*\n```\n"
#         f"Delta  : {g_mkt['delta']:.4f}\n"
#         f"Gamma  : {g_mkt['gamma']:.6f}\n"
#         f"Vega   : {g_mkt['vega_per_1pct']:.4f}\n"
#         f"Theta  : {g_mkt['theta_per_day']:.4f}\n"
#         f"Rho    : {g_mkt['rho_per_1pct']:.4f}\n"
#         "```"
#     )
#     await update.message.reply_text(msg, parse_mode="Markdown")

async def greeks(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /greeks [INSTRUMENT_NAME] - Show option Greeks (Delta, Gamma, Vega, Theta, Rho)
    Example: /greeks BTC-31DEC25-6000-C
    """
    if not context.args:
        await update.message.reply_text("Usage: /greeks BTC-31DEC25-60000-C")
        return
    _, _, msg, is_error = await get_greeks(context.args[0].upper())
    if is_error:
        await update.message.reply_text(msg)
        return
    await update.message.reply_text(msg, parse_mode="Markdown")

async def get_greeks(inst_name: str) -> tuple[dict, str, bool]:
    """
    /greeks [INSTRUMENT_NAME] - Show option Greeks (Delta, Gamma, Vega, Theta, Rho)
    Example: /greeks BTC-31DEC25-6000-C
    Returns
        raw: dict of raw val (any type)
        processed: dict of processed val in valid dp (str type)
        msg: telegram msg (str type)
        is_error:  True/False (bool type)
    """
    data, err = await bs_greeks_wrapper(inst_name, cache=_RFR_CACHE)
    if err: return {}, err, True
    g_mkt = data["g_mkt"]
    raw = {
        PRETTY_PARAMETERS.INSTRUMENT_NAME.value: inst_name,
        PRETTY_PARAMETERS.DELTA.value: g_mkt['delta'],
        PRETTY_PARAMETERS.GAMMA.value: g_mkt['gamma'],
        PRETTY_PARAMETERS.VEGA.value: g_mkt['vega_per_1pct'],
        PRETTY_PARAMETERS.THETA.value: g_mkt['theta_per_day'],
        PRETTY_PARAMETERS.RHO.value: g_mkt['rho_per_1pct']
    }
    processed = {
        PRETTY_PARAMETERS.INSTRUMENT_NAME.value: inst_name,
        PRETTY_PARAMETERS.DELTA.value: fnum(g_mkt['delta'], 4),
        PRETTY_PARAMETERS.GAMMA.value: fnum(g_mkt['gamma'], 6),
        PRETTY_PARAMETERS.VEGA.value: fnum(g_mkt['vega_per_1pct'], 4),
        PRETTY_PARAMETERS.THETA.value: fnum(g_mkt['theta_per_day'], 4),
        PRETTY_PARAMETERS.RHO.value: fnum(g_mkt['rho_per_1pct'], 4)
    }
    msg = (
        f"*{raw[PRETTY_PARAMETERS.INSTRUMENT_NAME.value]} — Greeks (mid→last(fresh)→mark)*\n```\n"
        f"{PRETTY_PARAMETERS.DELTA.value}  : {g_mkt['delta']:.4f}\n"
        f"{PRETTY_PARAMETERS.GAMMA.value}  : {g_mkt['gamma']:.6f}\n"
        f"{PRETTY_PARAMETERS.VEGA.value}   : {g_mkt['vega_per_1pct']:.4f}\n"
        f"{PRETTY_PARAMETERS.THETA.value}  : {g_mkt['theta_per_day']:.4f}\n"
        f"{PRETTY_PARAMETERS.RHO.value}    : {g_mkt['rho_per_1pct']:.4f}\n"
        "```"
    )
    return raw, processed, msg, False

# # === MAIN ===
# def main():
#     app = Application.builder().token(BOT_TOKEN).build()
#     app.add_handler(CommandHandler("start", start))
#     app.add_handler(CommandHandler("price", price))
#     app.add_handler(CommandHandler("basis", basis))
#     app.add_handler(CommandHandler("option", option))
#     app.add_handler(CommandHandler("greeks", greeks))
#     app.add_handler(CommandHandler("runsc", runsc))
#     app.add_handler(CommandHandler("runsp", runsp))
#     app.add_handler(CommandHandler("runbc", runbc))
#     app.add_handler(CommandHandler("runbp", runbp))
#     app.add_handler(CommandHandler("prob", prob))
#     app.add_handler(CommandHandler("misprice", misprice))
#     app.add_error_handler(error_handler)
    

#     print("Deribit bot running... Ctrl+C to stop.")
#     app.run_polling()

# if __name__ == "__main__":
#     main()
