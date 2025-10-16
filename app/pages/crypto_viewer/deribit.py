import logging
import requests
import math
import time
from datetime import datetime, timezone
from dotenv import load_dotenv
from scipy.stats import norm
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
import numpy as np
import certifi
import os, csv, io

from utils.enums_option import (
    PRETTY_OPTION_TYPE, PRETTY_PARAMETERS, PRETTY_RUNS_TYPE
)
from utils.string_formatter import (
    fnum, pct, fpct,
)

load_dotenv()

# Force requests to a working CA bundle (Windows-safe)
os.environ["SSL_CERT_FILE"] = certifi.where()
os.environ["REQUESTS_CA_BUNDLE"] = certifi.where()

# === CONFIG ===
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
DERIBIT_API_BASE = "https://www.deribit.com/api/v2"

# === LOGGING ===
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.WARNING
)

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

# === RISK-FREE RATE with robust fallbacks ===
def _yahoo_irx_rate(max_age_days: int = 30, retries: int = 2, backoff: float = 0.7) -> float | None:
    url = "https://query1.finance.yahoo.com/v8/finance/chart/%5EIRX"  # ^IRX = 3-month T-bill
    params = {"range": "3mo", "interval": "1d"}  # get last 3 months daily data; daily bars
    headers = {"User-Agent": "Mozilla/5.0"}  # to avoid beig blocked as a bot when requesting
    delay = backoff
    for _ in range(max(1, retries)):
        """
        Model:
        Grab the last 90 days' data of closed prices and find the first valid close to be used as the RFR.
        Sanity: Reasonably sound for normal daily/weekly options service using tele bots. 
                For HFT, use more sophisticated direct market data (e.g. median or weighted average).
        """
        try:
            r = requests.get(url, params=params, headers=headers, timeout=12, verify=certifi.where())
            r.raise_for_status()
            #ct = (r.headers.get("Content-Type") or "").lower()  # todo: remove if works
            ct = r.headers.get("Content-Type", "").lower()
            if r.status_code != 200 or "json" not in ct:
                logging.info(f"RFR Yahoo ^IRX skipped (status={r.status_code}, ct={ct})")
                return None
            j = r.json()
            #res = (j.get("chart") or {}).get("result") or []  # todo: remove if works
            res = j.get("chart", {}).get("result", [])
            if not res:
                logging.info("RFR Yahoo ^IRX empty result set")
                return None
            q = res[0].get("indicators", {}).get("quote", [])
            closes = q[0].get("close", []) if q else []
            #ts = res[0].get("timestamp", []) or []  # todo: remove if works
            ts = res[0].get("timestamp", [])
            if not closes or not ts:
                logging.info("RFR Yahoo ^IRX missing closes/timestamps")
                return None
            today = datetime.now(timezone.utc).date()

            # yahoo returns T-bills as annualized percentage e.g. 5.30%, not decimals
            for i in range(len(closes) - 1, -1, -1):
                c = closes[i]
                if c is None:
                    continue
                dt = datetime.fromtimestamp(ts[i], tz=timezone.utc).date()
                if (today - dt).days <= max_age_days:
                    val = float(c) / 100.0  # convert to decimals
                    if 0.0 <= val <= 0.15:
                        logging.info(f"RFR Yahoo ^IRX {dt.isoformat()} -> {val*100:.2f}%")
                        return val
            return None
        except Exception as e:
            logging.info(f"RFR Yahoo ^IRX attempt failed: {e}")
        time.sleep(delay)
        delay *= 2
    return None

def _fred_dgs3mo_csv(max_age_days: int = 30) -> float | None:
    try:
        url = "https://fred.stlouisfed.org/graph/fredgraph.csv"
        r = requests.get(url, params={"id": "DGS3MO"}, timeout=12, verify=certifi.where())  # 3-Month Treasury Constant Maturity Rate (Annualized)
        r.raise_for_status()
        today = datetime.now(timezone.utc).date()
        rows = list(csv.reader(io.StringIO(r.text)))
        for row in reversed(rows[1:]):
            if len(row) < 2:
                continue
            #d, v = row[0], row[1]  # todo: remove if works
            d, v = row
            if not v or v == ".":
                continue
            dt = datetime.fromisoformat(d).date()
            if (today - dt).days > max_age_days:
                continue
            # fred returns T-bills as annualized percentage e.g. 5.30%, not decimals
            val = float(v) / 100.0
            if 0.0 <= val <= 0.15:
                logging.warning(f"RFR FRED DGS3MO {d} -> {val*100:.2f}%")
                return val
    except Exception as e:
        logging.warning(f"RFR FRED DGS3MO failed: {e}")
    return None

def _treasury_yield_curve_csv(max_age_days: int = 30) -> float | None:
    try:
        url = "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/Daily_Treasury_Yield_Curve_Rates.csv"
        r = requests.get(url, timeout=12, verify=certifi.where())
        if r.status_code != 200:
            return None
        today = datetime.now(timezone.utc).date()
        reader = csv.DictReader(io.StringIO(r.text))
        for row in reversed(list(reader)):
            d = row.get("Date"); v = row.get("3 Mo")
            if not d or not v:
                continue
            try:
                dt = datetime.strptime(d, "%m/%d/%Y").date()
            except ValueError:
                try:
                    dt = datetime.strptime(d, "%Y-%m-%d").date()
                except Exception:
                    continue
            if v in ("", "N/A"):
                continue
            if (today - dt).days > max_age_days:
                continue
            val = float(v) / 100.0
            if 0.0 <= val <= 0.15:
                logging.warning(f"RFR Treasury CSV {dt.isoformat()} -> {val*100:.2f}%")
                return val
    except Exception as e:
        logging.warning(f"RFR Treasury CSV failed: {e}")
    return None

def get_risk_free_rate(ttl_seconds: int = 3 * 60 * 60) -> float:
    now = time.time()
    if _RFR_CACHE["val"] is not None and (now - _RFR_CACHE["t"] <= ttl_seconds):
        return _RFR_CACHE["val"]
    try:
        override = os.getenv("RFR_OVERRIDE")  # todo: what is this override for? when is it activated and how is the value determined?
        if override is not None:
            val = float(override)
            if 0.0 <= val <= 0.15:
                logging.warning(f"RFR override used: {val*100:.2f}%")
                _RFR_CACHE.update({"t": now, "val": val})
                return val
    except Exception:
        pass
    sources = (_fred_dgs3mo_csv, _treasury_yield_curve_csv, _yahoo_irx_rate)
    for fn in sources:
        try:
            val = fn()
        except Exception as e:
            logging.info(f"RFR source {fn.__name__} failed: {e}")
            val = None
        if val is not None:
            val = float(max(0.0, min(val, 0.15)))
            _RFR_CACHE.update({"t": now, "val": val})
            return val
    logging.warning("RFR: all sources failed; hard fallback 5.00%")
    _RFR_CACHE.update({"t": now, "val": 0.05})
    return 0.05

# === REALIZED VOL (BINANCE, no key) ===
def get_realized_vol(days: int = 30, use_ewma: bool = True, lambda_: float = 0.97, annualize_days: int = 365) -> float:
    url = "https://api.binance.com/api/v3/klines"
    resp = requests.get(
        url,
        params={"symbol": "BTCUSDT", "interval": "1d", "limit": days + 1},  #todo: why base it on BTCUSDT?
        timeout=10,
        verify=certifi.where()
    )
    if resp.status_code != 200 or "json" not in (resp.headers.get("Content-Type", "").lower()):
        return 0.40
    try:
        data = resp.json()
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
        rv = math.sqrt(var)
    else:
        rv = float(np.std(r, ddof=1))
         # stddev scaled to annualized volatility
    return rv * math.sqrt(annualize_days)

# # === INDEX SPOT (USD-first) ===
def _get_deribit_index_usd_first(base: str) -> float | None:
    """
    Returns the Deribit index price in USD if available, otherwise USDT/USDC.
    """
    for q in ("usd", "usdt", "usdc"):
        px = get_index_price(f"{base.lower()}_{q}")
        if px is not None:
            return float(px)
    return None

# # === Binance symbol for OHLC pulls ===
def _binance_symbol_for_base(base: str) -> str:
    base = base.upper()
    if base == "BTC": return "BTCUSDT"
    if base == "ETH": return "ETHUSDT"
    return f"{base}USDT"

def _fetch_binance_ohlc(symbol: str, days: int) -> tuple[list[float], list[float], list[float], list[float]] | None:
    """
    Returns arrays (O, H, L, C) of length >= days+1 if possible.
    """
    url = "https://api.binance.com/api/v3/klines"
    try:
        r = requests.get(url, params={"symbol": symbol, "interval": "1d", "limit": days + 2},
                        timeout=10, verify=certifi.where())
        r.raise_for_status()
        j = r.json()
        if not j or not isinstance(j, list):
            raise ValueError("Invalid OHLC data")
        O = [float(x[1]) for x in j]
        H = [float(x[2]) for x in j]
        L = [float(x[3]) for x in j]
        C = [float(x[4]) for x in j]
        return O, H, L, C
    except Exception as e:
        logging.warning(f"binance_ohlc failed: {e}")

# # === Realized Vol: Yang–Zhang (OHLC), adaptive by DTE ===
def _realized_vol_yang_zhang_from_ohlc(O, H, L, C, trading_days: int = 365) -> float | None:
    """
    Yang–Zhang variance:
      var = var(oc) + k * var(co) + (1-k) * mean( u*(u-c) + d*(d-c) )
      with oc = ln(O_t/C_{t-1}), co = ln(C_t/O_t), u = ln(H_t/O_t), d = ln(L_t/O_t)
      k = 0.34/(1.34 + (n+1)/(n-1))
    Returns annualized sigma.
    """
    n = len(C)
    if n < 2: 
        return None
    # build series for t=1..n-1
    oc = np.log(np.array(O[1:], float) / np.array(C[:-1], float))
    co = np.log(np.array(C[1:], float) / np.array(O[1:], float))
    u  = np.log(np.array(H[1:], float) / np.array(O[1:], float))
    d  = np.log(np.array(L[1:], float) / np.array(O[1:], float))

    # winsorize 1% tails for robustness
    def _wins(a):
        lo, hi = np.quantile(a, 0.01), np.quantile(a, 0.99)
        return np.clip(a, lo, hi)
    oc, co, u, d = _wins(oc), _wins(co), _wins(u), _wins(d)

    m = len(co)
    if m < 3:
        return None
    var_oc = float(np.var(oc, ddof=1))
    var_co = float(np.var(co, ddof=1))
    rs = float(np.mean(u * (u - co) + d * (d - co)))
    k = 0.34 / (1.34 + (m + 1) / (m - 1)) if m > 1 else 0.34
    var_yz = var_oc + k * var_co + (1.0 - k) * rs  # daily variance
    # returned annualized sigma i.e. stddev
    return math.sqrt(max(0.0, var_yz)) * math.sqrt(trading_days)

def get_realized_vol_yz_dynamic(base: str, dte_days: float) -> float:
    """
    Adaptive window:
      DTE <= 7  -> 14 days
      7 < DTE <= 30 -> 30 days
      DTE > 30  -> 45 days
    Falls back to your existing close-to-close EWMA if needed.
    """
    if dte_days <= 7:
        lb = 14
    elif dte_days <= 30:
        lb = 30
    else:
        lb = 45
    try:
        symbol = _binance_symbol_for_base(base)
        O, H, L, C = _fetch_binance_ohlc(symbol, lb)
        yz = _realized_vol_yang_zhang_from_ohlc(O, H, L, C, trading_days=365)
        if yz and 0.0001 <= yz <= 5.0:
            return float(yz)
    except Exception as e:
        logging.warning(f"get_realized_vol_yz_dynamic failed: {e}")
        pass
    # fallback: your original CC/EWMA on BTC (kept for resilience)
    return float(get_realized_vol(days=30))

# # === API HELPERS ===
def get_index_price(index_name: str, ttl: int = 5) -> float | None:
    v = _cget(_INDEX_CACHE, index_name, ttl)
    if v is not None:
        return v
    url = f"{DERIBIT_API_BASE}/public/get_index_price"

    try:
        res = requests.get(
                url,
                params={"index_name": index_name},
                timeout=10,
                verify=certifi.where()
            )
        res.raise_for_status()
        data = res.json()
        price = data.get("result", {}).get("index_price")
        if price is not None:
            price = float(price)
            _cset(_INDEX_CACHE, index_name, price)
        return price
    except Exception as e:
        logging.warning(f"get_index_price {index_name} failed: {e}")

# todo: relook after normal options completed
def get_futures_instruments(base: str) -> list[dict] | None:
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

def get_option_instruments(base: str) -> list[dict] | None:
    """
    Robust fetch. Deribit wants 'expired' as lowercase string 'false'/'true'.
    Try variants; fall back to no-parameter.
    """
    url = f"{DERIBIT_API_BASE}/public/get_instruments"
    base = base.upper()
    variants = [
        {"currency": base, "kind": "option", "expired": "false"},
        {"currency": base, "kind": "option"},
    ]
    for params in variants:
        try:
            resp = requests.get(url, params=params, timeout=12, verify=certifi.where())
            j = resp.json()
            if isinstance(j, dict) and "error" in j:
                continue
            result = j.get("result", [])
            if result:
                return result
        except Exception:
            continue
    return []

def get_option_instruments_cached(base: str, ttl: int = 60) -> list[dict] | None:
    """
    Cached version of get_option_instruments.
    """
    base = base.upper()
    v = _cget(_OPT_CACHE, base, ttl)
    if v is not None:
        return v
    data = get_option_instruments(base)
    return _cset(_OPT_CACHE, base, data)

def get_book_summary_by_currency(
        base: str,
        kind: str = "option",
        ttl: int = 10
    ) -> tuple[list[dict], dict]:
    """
    Bulk quotes. Returns list and a dict keyed by instrument_name.
    """
    key = (base.upper(), kind)
    v = _cget(_BOOK_CACHE, key, ttl)
    if v is not None:
        arr = v
    else:
        url = f"{DERIBIT_API_BASE}/public/get_book_summary_by_currency"
        try:
            res = requests.get(
                    url,
                    params={"currency": base.upper(), "kind": kind},
                    timeout=12,
                    verify=certifi.where()
                )
            res.raise_for_status()
            arr = res.json().get("result", []) or []
            _cset(_BOOK_CACHE, key, arr)
        except Exception as e:
            logging.warning(f"get_book_summary_by_currency {base} {kind} failed: {e}")
            arr = []
    m = {x.get("instrument_name"): x for x in arr if "instrument_name" in x}
    return arr, m

def get_ticker(instrument_name: str) -> dict | None:
    """
    Ticker info for a single instrument. E.g. "BTC-30JUN23-30000-C"
    """
    url = f"{DERIBIT_API_BASE}/public/ticker"
    
    try:
        res = requests.get(
                url,
                params={"instrument_name": instrument_name},
                timeout=10, verify=certifi.where()
            )
        data = res.json()
        return data.get("result", {})
    except Exception as e:
        logging.warning(f"get_ticker {instrument_name} failed: {e}")
        return None

def get_instrument(instrument_name: str) -> dict | None:
    """
    Instrument details for a single instrument. E.g. "BTC-30JUN23-30000-C"
    """
    url = f"{DERIBIT_API_BASE}/public/get_instrument"
    try:
        res = requests.get(
                url,
                params={"instrument_name": instrument_name},
                timeout=10, verify=certifi.where()
            )
        data = res.json()
        return data.get("result", {})
    except Exception as e:
        logging.warning(f"get_instrument {instrument_name} failed: {e}")
        return None

# ---------- PRICE SELECTION HELPERS (MID → LAST(if fresh) → MARK) ----------
STALE_LAST_SECONDS = 300  # 5 minutes

def _get_last_trade_ts_ms(inst_name: str) -> int | None:
    """
    Returns the timestamp (ms) of the last trade for the given instrument, or None if not found.
    """
    try:
        url = f"{DERIBIT_API_BASE}/public/get_last_trades_by_instrument"
        r = requests.get(
                url,
                params={
                    "instrument_name": inst_name,
                    "count": 1,
                    "include_old": "true"
                },
                timeout=8, verify=certifi.where()
            )
        r.raise_for_status()
        res = r.json().get("result", [])
        if isinstance(res, dict) and "trades" in res:
            res = res["trades"]
        if isinstance(res, list) and res:
            ts = int(res[0].get("timestamp") or 0)
            return ts if ts > 0 else None
    except Exception as e:
        logging.warning(f"_get_last_trade_ts_ms {inst_name} failed: {e}")
        pass
    return None

def _pick_price_mid_last_mark(
        bid, ask, last, last_ts_ms, mark, staleness_sec: int = STALE_LAST_SECONDS
    ) -> float | None:
    """
    Pick price in order of preference:
      1. mid of bid/ask if both present and >0
      2. last if present, >0, and not stale (within staleness_sec)
      3. mark if present and >0
    Returns float price or None.
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

def _usd_option_mid(
        inst: dict, ticker: dict | None, summary: dict | None, spot_fallback: float
    ) -> float:
    """
    USD mid using ticker bid/ask (prefer), otherwise last (if fresh), otherwise mark;"""
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
                last_ts = _get_last_trade_ts_ms(inst_name)
    except Exception:
        last_ts = None

    raw_px = _pick_price_mid_last_mark(bid, ask, last, last_ts, mark)
    if quote in ["USD", "USDC"]:
        return float(raw_px or 0.0)
    return float((raw_px * und) if (raw_px and und) else 0.0)

def _raw_option_mid(inst: dict, ticker: dict | None, summary: dict | None) -> float:
    """
    Raw mid using ticker bid/ask (prefer), otherwise last (if fresh), otherwise mark; no USD conversion.
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
                last_ts = _get_last_trade_ts_ms(inst_name)
    except Exception:
        last_ts = None

    return float(_pick_price_mid_last_mark(bid, ask, last, last_ts, mark) or 0.0)

def _pick_min_spot_index(base: str) -> tuple[float | None, str | None]:
    """
    Picks the lowest available index price among USD/USDT/USDC for the given base.
    Returns (price, label) or (None, None) if none found.
    """
    choices = []
    for ccy in ("usd", "usdt", "usdc"):
        px = get_index_price(f"{base.lower()}_{ccy}")
        if px:
            choices.append((float(px), ccy.upper()))
    if not choices:
        return None, None
    # return (spot_price, label)
    return min(choices, key=lambda x: x[0])

# NEW: spot reference for /basis (PERPETUAL mid→last(fresh)→mark, else lowest index)
def get_spot_reference(
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
    _, futmap = get_book_summary_by_currency(base, "future", ttl=5)
    perp = next((n for n in futmap.keys() if "PERPETUAL" in n.upper()), None)
    if perp:
        s = futmap.get(perp, {}) or {}
        bid = float(s.get("bid_price") or 0.0)
        ask = float(s.get("ask_price") or 0.0)
        if bid > 0 and ask > 0:
            return (bid + ask) / 2.0, "Perp (mid)"

        last = s.get("last_price")
        if last:
            ts = _get_last_trade_ts_ms(perp)
            if ts:
                age = (datetime.now(timezone.utc) - datetime.fromtimestamp(ts / 1000, tz=timezone.utc)).total_seconds()
                if age <= stale_sec:
                    return float(last), "Perp (last)"

        mark = s.get("mark_price")
        if mark:
            return float(mark), "Perp (mark)"

    # Fallback: choose the lowest available index (USD/USDT/USDC)
    idx, ccy = _pick_min_spot_index(base)
    if idx is not None:
        return float(idx), f"Index {ccy}"
    return None, "n/a"

# ========= IV surface + RV forecasting (HAR / GARCH) =========

def _unique_live_expiries(base: str, limit: int | None = None):
    """
    Returns sorted list of unique future expiration timestamps (ms) for the given base.
    """
    arr = get_option_instruments_cached(base)
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    exps = sorted({
                    int(x["expiration_timestamp"]) for x in arr 
                        if x.get("expiration_timestamp") and
                        int(x["expiration_timestamp"]) > now_ms
                })
    return exps if limit is None else exps[:limit]

def _usd_mid_from_summary_for_inst(inst: dict, summ: dict, spot_usd: float) -> float:
    """
    USD mid using summary bid/ask (prefer), otherwise mark; handles coin vs USD quotes.
    If quote is not USD/USDC, convert using spot_usd.
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
    Build IV surface rows for the given expiry timestamp (ms).
    Each row is a dict with keys: name, K, type, T, iv, usd_mid.
    Returns list of dicts with fields:
        {'name','K','type','T','iv','usd_mid'}
    Only strikes within [S*(1-band), S*(1+band)].
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

# ---- Daily realized-vol series (Yang–Zhang style per-day proxy) ----
def _daily_yz_series(base: str, lookback_days: int = 120) -> np.ndarray:
    """
    Build a daily realized-vol *series*. We approximate daily YZ variance per day as:
      yz_t = oc_t^2 + k*co_t^2 + (1-k)*RS_t,
    where RS_t = u_t*(u_t - co_t) + d_t*(d_t - co_t),
          oc_t = ln(O_t/C_{t-1}), co_t = ln(C_t/O_t),
          u_t = ln(H_t/O_t), d_t = ln(L_t/O_t), k≈0.34.
    Return daily sigma_t (not annualized).
    """
    symbol = _binance_symbol_for_base(base)
    O, H, L, C = _fetch_binance_ohlc(symbol, lookback_days + 2)
    if len(C) < 3:
        return np.array([])
    O = np.array(O, float); H = np.array(H, float); L = np.array(L, float); C = np.array(C, float)
    oc = np.log(O[1:] / C[:-1])
    co = np.log(C[1:] / O[1:])
    u  = np.log(H[1:] / O[1:])
    d  = np.log(L[1:] / O[1:])
    # winsorize 1% tails
    def _wins(a):
        lo, hi = np.quantile(a, 0.01), np.quantile(a, 0.99)
        return np.clip(a, lo, hi)
    oc, co, u, d = _wins(oc), _wins(co), _wins(u), _wins(d)
    k = 0.34
    RS = u*(u - co) + d*(d - co)
    yz_var = oc*oc + k*(co*co) + (1.0 - k)*RS
    yz_var = np.clip(yz_var, 0.0, None)
    return np.sqrt(yz_var)  # daily sigma_t

# ---- HAR forecast (next-day, annualized) ----
def _har_forecast_annualized(base: str, min_hist: int = 60) -> float | None:  # todo: document on gdoc
    """
    HAR forecast using daily YZ series.
    Requires at least min_hist days of history.
    Returns next-day annualized sigma, or None if not enough data.
    """
    rv_d = _daily_yz_series(base, lookback_days=max(120, min_hist+30))
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
        X.append([1.0, math.log(d), math.log(w), math.log(m)])
        y.append(math.log(rv_d[t]))
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
    ln_next = float(beta[0] + beta[1]*math.log(max(d,1e-9)) + beta[2]*math.log(max(w,1e-9)) + beta[3]*math.log(max(m,1e-9)))
    daily_sigma = max(1e-8, math.exp(ln_next))
    return daily_sigma * math.sqrt(365.0)  # annualized

# ---- GARCH(1,1) forecast (next-day, annualized; simple calibration) ----
def _garch11_forecast_annualized(base: str, lookback_days: int = 365) -> float | None:  # todo: document on gdoc
    """
    Simple GARCH(1,1) forecast using close-to-close log returns.
    Returns next-day annualized sigma, or None if not enough data.
    """
    symbol = _binance_symbol_for_base(base)
    try:
        _O, _H, _L, C = _fetch_binance_ohlc(symbol, lookback_days + 2)
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
    for ri in r:
        sigma2 = omega + alpha * (ri**2) + beta * sigma2
    # next-day variance
    sigma2_f = omega + alpha * (r[-1]**2) + beta * sigma2
    daily_sigma = math.sqrt(max(1e-12, sigma2_f))
    return daily_sigma * math.sqrt(365.0)

def _forecast_rv_annualized(base: str, model: str = "har") -> float | None:
    """
    Forecast next-day annualized realized vol using specified model.
    model: "har" (default) or "garch"
    Returns annualized sigma or None if not enough data.
    """
    model = (model or "har").lower()
    if model == "garch":
        f = _garch11_forecast_annualized(base)
        if f is not None:
            return f
        # fall back to HAR
    return _har_forecast_annualized(base)

def _zscore_list(vals: list[float]) -> list[float]:
    """
    Returns z-scores of the input list.
    If len(vals)<3 or stddev is too small, returns zeros.
    """
    if not vals or len(vals) < 3:
        return [0.0 for _ in vals]
    m = float(np.mean(vals)); s = float(np.std(vals, ddof=1))
    if s <= 1e-12:
        return [0.0 for _ in vals]
    return [(v - m)/s for v in vals]

# === BLACK–SCHOLES HELPERS ===
def bs_price(S, K, T, r, sigma, option_type="call"):  # todo: document on gdoc
    """
    Black–Scholes option price.
        S: underlying price
        K: strike price
        T: time to expiration in years
        r: risk-free rate (annualized, decimal)
        sigma: volatility (annualized, decimal)
        option_type: "call" or "put"
    Returns option price as float.
    """
    if T <= 0 or sigma <= 0:
        return max(0.0, (S - K) if option_type == "call" else (K - S))
    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    if option_type == "call":
        return S * norm.cdf(d1) - K * math.exp(-r * T) * norm.cdf(d2)
    else:
        return K * math.exp(-r * T) * norm.cdf(-d2) - S * norm.cdf(-d1)

def implied_vol(target_price, S, K, T, r, option_type="call"):  # todo: document on gdoc
    """
    Implied volatility using Newton-Raphson method.
    Returns sigma as float.
    """
    if target_price <= 0:
        return 0.0001
    sigma = 0.5
    for _ in range(60):
        price = bs_price(S, K, T, r, sigma, option_type)
        d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
        vega = S * norm.pdf(d1) * math.sqrt(T)
        diff = price - target_price
        if abs(diff) < 1e-6:
            return sigma
        if vega < 1e-8:
            break
        sigma -= diff / vega
        sigma = max(min(sigma, 5.0), 1e-6)
    return sigma

def bs_itm_probability(S, K, T, sigma, option_type="call", r=0.0, q=0.0) -> float:
    """
    Black–Scholes probability of expiring in-the-money.
        S: underlying price
        K: strike price
        T: time to expiration in years
        sigma: volatility (annualized, decimal)
        option_type: "call" or "put"
        r: risk-free rate (annualized, decimal), default 0.0
        q: dividend yield (annualized, decimal), default 0.0
    Returns probability as float in [0,1].
    """
    if T <= 0 or sigma <= 0:
        return 1.0 if (option_type == "call" and S > K) or (option_type == "put" and S < K) else 0.0
    d1 = (math.log(S / K) + (r - q + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    return norm.cdf(d2) if option_type == "call" else norm.cdf(-d2)

def bs_greeks(S, K, T, r, sigma, option_type="call") -> dict:  # todo: document on gdoc
    """
    Black–Scholes Greeks.
        S: underlying price
        K: strike price
        T: time to expiration in years
        r: risk-free rate (annualized, decimal)
        sigma: volatility (annualized, decimal)
        option_type: "call" or "put"
    Returns dict with keys: delta, gamma, vega_per_1pct, theta_per_day, rho_per_1pct
    """
    if T <= 0 or sigma <= 0:
        intrinsic_delta = 1.0 if (option_type == "call" and S > K) else (-1.0 if (option_type == "put" and S < K) else 0.0)
        return {"delta": intrinsic_delta, "gamma": 0.0, "vega_per_1pct": 0.0, "theta_per_day": 0.0, "rho_per_1pct": 0.0}
    sqrtT = math.sqrt(T)
    d1 = (math.log(S / K) + (r + 0.5 * sigma * sigma) * T) / (sigma * sqrtT)
    d2 = d1 - sigma * sqrtT
    Nd1, Nd2, nd1 = norm.cdf(d1), norm.cdf(d2), norm.pdf(d1)
    disc = math.exp(-r * T)
    delta = Nd1 if option_type == "call" else (Nd1 - 1.0)
    gamma = nd1 / (S * sigma * sqrtT)
    vega_per_1pct = (S * nd1 * sqrtT) / 100.0
    theta_time = -(S * nd1 * sigma) / (2.0 * sqrtT)
    theta_rate = (-r * K * disc * Nd2) if option_type == "call" else (+r * K * disc * norm.cdf(-d2))
    theta_per_day = (theta_time + theta_rate) / 365.0
    rho_per_1pct = ((K * T * disc * Nd2) if option_type == "call" else (-K * T * disc * norm.cdf(-d2))) / 100.0
    return {"delta": delta, "gamma": gamma, "vega_per_1pct": vega_per_1pct, "theta_per_day": theta_per_day, "rho_per_1pct": rho_per_1pct}

def bs_greeks_wrapper(instrument_name: str) -> tuple[dict | None, str | None]:
    """
    Wrapper to fetch data and compute Greeks for the given option instrument.
    Returns (greeks_dict, error_message) where greeks_dict has keys:
        underlying_price, strike, type, T, r, iv, fair_vol, g_mkt, g_fair
    or (None, error_message) if error.
    """
    ticker = get_ticker(instrument_name)
    if not ticker:
        return None, "Invalid or unknown option instrument."
    underlying_price = ticker.get("underlying_price")
    if not underlying_price:
        return None, "Missing option data."
    inst = get_instrument(instrument_name)
    if not inst:
        return None, "Instrument metadata missing."
    strike = float(inst.get("strike"))
    option_type = "call" if inst.get("option_type") == "call" else "put"
    expiry_ts = inst.get("expiration_timestamp")
    expiry = datetime.fromtimestamp(expiry_ts / 1000, tz=timezone.utc)
    T = max((expiry - datetime.now(timezone.utc)).days / 365, 0.0001)

    base = instrument_name.split("-")[0].upper()
    _arr, bm = get_book_summary_by_currency(base, "option", ttl=8)
    usd_mid = _usd_option_mid(inst, ticker, bm.get(instrument_name, {}), float(underlying_price))
    if usd_mid <= 0:
        return None, "Could not compute a valid mid/last/mark price."

    r = get_risk_free_rate()
    iv = implied_vol(usd_mid, float(underlying_price), strike, T, r, option_type)
    fair_vol = get_realized_vol(30)
    g_mkt = bs_greeks(float(underlying_price), strike, T, r, iv, option_type)
    g_fair = bs_greeks(float(underlying_price), strike, T, r, fair_vol, option_type)
    return {
        "underlying_price": underlying_price, "strike": strike, "type": option_type,
        "T": T, "r": r, "iv": iv, "fair_vol": fair_vol, "g_mkt": g_mkt, "g_fair": g_fair
    }, None

# === RUNS (ATM per ALL expiries) ===
def _find_atm_instruments_all_expiries(base: str, opt_type: str) -> tuple[list[dict], float | None]:
    """
    Finds ATM option instruments for ALL future expiries for the given base and option type.
    Returns (list_of_dicts, spot_price) where each dict has keys:
        date (e.g. "30JUN23"), tenor (days), strike, premium_usd, premium_coin, open_interest, instrument_name, underlying, quote_ccy"
    or ([], None) if spot could not be fetched.
    """
    base = base.upper()
    spot = get_index_price(f"{base.lower()}_usd")
    if not spot:
        spot = get_index_price(f"{base.lower()}_usdt")
    if not spot:
        return [], None
    spot = float(spot)
    instruments = get_option_instruments_cached(base)
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
    _, bm = get_book_summary_by_currency(base, "option", ttl=10)

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
            last_ts = _get_last_trade_ts_ms(name)
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

async def _runs_common(update: Update, context: ContextTypes.DEFAULT_TYPE, action_symbol: str, opt_type: str) -> None:
    """
    Common handler for /run{b|s}{c|p} commands.
    action_symbol: "B" or "S"
    opt_type: "call" or "put"
    """
    # Try to determine base from args; default to BTC
    base = "BTC"
    if context.args and context.args[0].upper() in ["BTC", "ETH"]:
        base = context.args[0].upper()
    _, msg, is_error = _get_runs_common(base, action_symbol, opt_type)
    if is_error:
        await update.message.reply_text(msg)
        return
    await update.message.reply_text(msg, parse_mode="Markdown")

def _get_runs_common(base: str, action_symbol: str, opt_type: str) -> tuple[list, str, bool]:
    """
    Common handler for /run{b|s}{c|p} commands.
    action_symbol: "B" or "S"
    opt_type: "call" or "put"
    """
    # fetch ATM instruments for all expiries for the given base and opt_type
    rows, spot = _find_atm_instruments_all_expiries(base, opt_type)
    if rows == [] and spot is None:  # spot fetch failed
        return {}, f"Could not fetch spot for {base}.", True
    if not rows:  # no expiries found
        return {}, f"No expiries found for {base} {opt_type}s.", True
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
    body = ""
    res = []
    for r in rows:
        res.append([r['date'], r['tenor'], r['strike'], action_symbol, ('C' if opt_type=='call' else 'P'),
                    r['premium_usd'], r['premium_coin'], r['open_interest']])
        body += (
            f"{r['date']:<9} {r['tenor']:>3} {r['strike']:>9,.0f} {action_symbol:>3} {('C' if opt_type=='call' else 'P'):>4} "
            f"{r['premium_usd']:>10,.2f} {r['premium_coin']:>8,.6f} {r['open_interest']:>6}\n"
        )
    msg = header + body + "```"
    return res, msg, False

def _get_all_runs(base: str) -> dict[tuple[list, str, bool]]:
    """
    Get all 4 runs (sell call, sell put, buy call, buy put) for the given base.
    Returns (runs_dict, msg, is_error) where runs_dict has keys:
        'Sell Call', 'Sell Put', 'Buy Call', 'Buy Put'
    Each value is a tuple of data list, telegram msg string, is_error bool
        The data list has rows with fields:
            [date, tenor, strike, action_symbol, type, premium_usd, premium_coin, open_interest]
    i.e (data, msg, False) if success,
    or ([], msg, True) if error.
    """
    runs = {}
    runs_types = [
                    ("S", "call", PRETTY_RUNS_TYPE.SELL_CALL.value),
                    ("S", "put", PRETTY_RUNS_TYPE.SELL_PUT.value),
                    ("B", "call", PRETTY_RUNS_TYPE.BUY_CALL.value),
                    ("B", "put", PRETTY_RUNS_TYPE.BUY_PUT.value)
                ]
    for action_symbol, opt_type, key in runs_types:
        res, msg, is_error = _get_runs_common(base, action_symbol, opt_type)
        runs[key] = (res, msg, is_error)
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
def prob_itm_all(instrument_name: str) -> tuple[dict | None, str | None]:
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
    inst = get_instrument(instrument_name)
    if not inst:
        return None, "Invalid or unknown option instrument."
    tkr = get_ticker(instrument_name)
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

    _arr, bm = get_book_summary_by_currency(base, "option", ttl=8)
    usd_mid = _usd_option_mid(inst, tkr, bm.get(instrument_name, {}), S)
    if usd_mid <= 0:
        return None, "Option price unavailable."

    r = get_risk_free_rate()
    iv_mkt = implied_vol(usd_mid, S, K, T, r, option_type)
    p_bs = bs_itm_probability(S, K, T, iv_mkt, option_type, r=r, q=0.0) if iv_mkt else None

    instruments = get_option_instruments_cached(base)
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
        res, err = prob_itm_all(instrument_name)
        if err:
            await update.message.reply_text(err)
            return
        S = res["inputs"]["S"]; K = res["inputs"]["K"]; T = res["inputs"]["T_years"]
        typ = res["inputs"]["type"]; r  = res["inputs"]["r"]
        iv = res["inputs"]["iv"]
        pbs = res["probs"]["bs"]; psurf = res["probs"]["surface"]; pmc = res["probs"]["mc"]; pen = res["probs"]["ensemble"]
        w_bs = res["weights"]["bs"]; w_surf = res["weights"]["surface"]; w_mc = res["weights"]["mc"]

        def pct(x): return "n/a" if x is None else f"{x*100:.2f}%"
        def fnum(x, n=2): return f"{x:,.{n}f}"

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
        msg = f"*{instrument_name} — ITM Probability*\n" + "```\n" + "\n".join(lines) + "\n```"
        await update.message.reply_text(msg, parse_mode="Markdown")
    except Exception as e:
        logging.exception(e)
        await update.message.reply_text("Error computing ITM probability.")

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
    S = _get_deribit_index_usd_first(base)
    if S is None:
        await update.message.reply_text(f"Could not fetch {base} index price.")
        return
    S = float(S)
    r = get_risk_free_rate()
    _arr, bm = get_book_summary_by_currency(base, "option", ttl=8)
    instruments = get_option_instruments_cached(base)
    inst_map = {x["instrument_name"]: x for x in instruments}

    # RV forecast (annualized)
    rv_for = _forecast_rv_annualized(base, model=model)
    if rv_for is None:
        await update.message.reply_text("Could not compute RV forecast (HAR/GARCH).")
        return

    expiries = _unique_live_expiries(base, limit=n_exp)
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
    await update.message.reply_text("\n".join(out_lines), parse_mode="Markdown")

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
        "/prob  <code>BTC-31DEC25-60000-C</code> – ITM Probability\n"
        "/misprice [BTC|ETH] [Nexp] [har|garch] [band] – IV surface vs RV forecast; flags top mispricings by VRP z‑score\n"

    )
    await update.message.reply_text(text, parse_mode="HTML")
    print(chat_id)  # todo: remove when done
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
#     idx_usd = get_index_price(f"{base.lower()}_usd")
#     idx_usdt = get_index_price(f"{base.lower()}_usdt")
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
#     _, bm_fut = get_book_summary_by_currency(base, "future", ttl=5)

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
#     tkr = get_ticker(inst_name) or {}

#     # Compose prices with hierarchy mid -> last (fresh) -> mark
#     bid = tkr.get("best_bid_price") or summ.get("bid_price")
#     ask = tkr.get("best_ask_price") or summ.get("ask_price")
#     last = tkr.get("last_price") or summ.get("last_price")
#     mark = tkr.get("mark_price") or summ.get("mark_price")
#     last_ts = None
#     if (not bid or bid <= 0 or not ask or ask <= 0) and last and last > 0:
#         last_ts = _get_last_trade_ts_ms(inst_name)
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
    """
    base = "BTC"
    if context.args:
        base = context.args[0].upper()

    lines, msg, is_error = get_price(base)
    if is_error:
        await update.message.reply_text(msg)
        return
    
    await update.message.reply_text(msg, parse_mode="Markdown")

def get_price(base: str) -> tuple[list[str], str, bool]:
    """
    /price [BTC|ETH] - Show spot, future quotes, 24h stats
    """
    # Spot (Index) — prefer USD, fall back to USDT
    idx_usd = get_index_price(f"{base.lower()}_usd")
    idx_usdt = get_index_price(f"{base.lower()}_usdt")
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
    _, bm_fut = get_book_summary_by_currency(base, "future", ttl=5)

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
    tkr = get_ticker(inst_name) or {}

    # Compose prices with hierarchy mid -> last (fresh) -> mark
    bid = tkr.get("best_bid_price") or summ.get("bid_price")
    ask = tkr.get("best_ask_price") or summ.get("ask_price")
    last = tkr.get("last_price") or summ.get("last_price")
    mark = tkr.get("mark_price") or summ.get("mark_price")
    last_ts = None
    if (not bid or bid <= 0 or not ask or ask <= 0) and last and last > 0:
        last_ts = _get_last_trade_ts_ms(inst_name)
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

    spot, spot_src = get_spot_reference(base)
    if spot is None:
        await update.message.reply_text(f"Could not fetch spot for {base}.")
        return

    futs = [f for f in get_futures_instruments(base)
            if "PERPETUAL" not in (f.get("instrument_name") or "").upper()]
    if not futs:
        await update.message.reply_text(f"No dated futures found for {base}.")
        return

    _, bm = get_book_summary_by_currency(base, "future", ttl=5)
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
            last_ts = _get_last_trade_ts_ms(nm)

        mid = _pick_price_mid_last_mark(bid, ask, last, last_ts, mark)
        if not mid:
            # fallback: pull from ticker as well
            tkr = get_ticker(nm) or {}
            bid = tkr.get("best_bid_price"); ask = tkr.get("best_ask_price")
            last = tkr.get("last_price");     mark = tkr.get("mark_price")
            last_ts = None
            if (not bid or bid <= 0 or not ask or ask <= 0) and last and last > 0:
                last_ts = _get_last_trade_ts_ms(nm)
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
#         inst = get_instrument(inst_name)
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
#         S = _get_deribit_index_usd_first(base)
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
#         _, bm = get_book_summary_by_currency(base, "option", ttl=8)
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
#         r = get_risk_free_rate()
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
        _, msg, is_error = get_option(inst_name)
        if is_error:
            await update.message.reply_text(msg)
            return
        await update.message.reply_text(msg, parse_mode="Markdown")
    except Exception as e:
        logging.exception(e)
        await update.message.reply_text("Error analyzing option.")

def get_option(inst_name: str) -> tuple[dict, str, bool]:
    """
    /option [INSTRUMENT_NAME] - Option valuation vs realized vol
    Example: /option BTC-31DEC25-60000-C
    """
    try:
        inst = get_instrument(inst_name)
        if not inst:
            return {}, "Invalid or unknown option instrument.", True

        base = inst_name.split("-")[0].upper()
        quote_ccy = inst.get("quote_currency", "").upper()

        # Inverse-only guard (coin-settled BTC/ETH options)
        if quote_ccy not in ("BTC", "ETH"):
            return {}, "This looks like a USD/USDC-settled option.\n" \
                    "This command supports only inverse coin-settled options (BTC/ETH).", True

        # Deribit index spot (USD-first)
        S = _get_deribit_index_usd_first(base)
        if S is None:
            return {}, f"Could not fetch {base} index price.", True
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
        _, bm = get_book_summary_by_currency(base, "option", ttl=8)
        summ = bm.get(inst_name, {})
        bid = float(summ.get("bid_price", 0.0))
        ask = float(summ.get("ask_price", 0.0))
        if not (bid > 0 and ask > 0):
            return {}, "No live bid/ask — cannot compute coin mid for this option.", True
        coin_mid = (bid + ask) / 2.0

        # USD conversion via index spot
        usd_mid = coin_mid * S

        # RFR and Market IV (from BS)
        r = get_risk_free_rate()
        iv = implied_vol(usd_mid, S, K, T_years, r, opt_type)

        # Realized vol (Yang–Zhang, adaptive by DTE)
        rv = get_realized_vol_yz_dynamic(base, dte_days)

        # Fair price under RV and Diff
        fair_price = bs_price(S, K, T_years, r, rv, opt_type)
        diff = usd_mid - fair_price
        status = "Overpriced" if diff > 0 else "Underpriced"

        # Pretty print (same style as your screenshot)
        coin_sym = base
        res = {
            PRETTY_PARAMETERS.INSTRUMENT_NAME.value: inst_name,
            PRETTY_PARAMETERS.SPOT_PRICE.value: fnum(S),
            PRETTY_PARAMETERS.STRIKE_PRICE.value: fnum(K),
            PRETTY_PARAMETERS.OPTION_TYPE.value: opt_type.upper(),
            PRETTY_PARAMETERS.DAYS_TO_EXPIRY.value: dte_days,
            PRETTY_PARAMETERS.INTEREST_RATE.value: pct(r),
            PRETTY_PARAMETERS.OPTION_MID.value+' (' + coin_sym + ')': coin_mid,
            PRETTY_PARAMETERS.OPTION_MID.value+' (USD)': usd_mid,
            PRETTY_PARAMETERS.FAIR_PRICE.value: fair_price,
            PRETTY_PARAMETERS.PRICE_DIFF.value: diff,
            PRETTY_PARAMETERS.IMPLIED_VOLATILITY.value: pct(iv),
            PRETTY_PARAMETERS.REALIZED_VOLATILITY_YZ.value: pct(rv),
            PRETTY_PARAMETERS.STATUS.value: status
        }
        msg = (
            f"*{res[PRETTY_PARAMETERS.INSTRUMENT_NAME.value]} — Option Valuation*\n"
            "```\n"
            f"{(PRETTY_PARAMETERS.SPOT_PRICE.value+' (USD)'):<18}: {res[PRETTY_PARAMETERS.SPOT_PRICE.value]:>12}\n"
            f"{(PRETTY_PARAMETERS.STRIKE_PRICE.value+' (USD)'):<18}: {res[PRETTY_PARAMETERS.STRIKE_PRICE.value]:>12}\n"
            f"{PRETTY_PARAMETERS.OPTION_TYPE.value:<18}: {res[PRETTY_PARAMETERS.OPTION_TYPE.value]:>12}\n"
            f"{(PRETTY_PARAMETERS.DAYS_TO_EXPIRY.value+' (days)'):<18}: {res[PRETTY_PARAMETERS.DAYS_TO_EXPIRY.value]:>12.1f}\n"
            f"{PRETTY_PARAMETERS.INTEREST_RATE.value:<18}: {res[PRETTY_PARAMETERS.INTEREST_RATE.value]:>12}\n"
            f"{(PRETTY_PARAMETERS.OPTION_MID.value+' (' + coin_sym + ')'):<18}: {res[PRETTY_PARAMETERS.OPTION_MID.value+' (' + coin_sym + ')']:>12,.6f}\n"
            f"{(PRETTY_PARAMETERS.OPTION_MID.value+' (USD)'):<18}: {res[PRETTY_PARAMETERS.OPTION_MID.value+' (USD)']:>12,.2f}\n"
            f"{(PRETTY_PARAMETERS.FAIR_PRICE.value+' (USD)'):<18}: {res[PRETTY_PARAMETERS.FAIR_PRICE.value]:>12,.2f}\n"
            f"{PRETTY_PARAMETERS.PRICE_DIFF.value+' (USD)':<18}: {res[PRETTY_PARAMETERS.PRICE_DIFF.value]:>12,.2f}\n"
            f"{PRETTY_PARAMETERS.IMPLIED_VOLATILITY.value:<18}: {res[PRETTY_PARAMETERS.IMPLIED_VOLATILITY.value]:>12}\n"
            f"{PRETTY_PARAMETERS.REALIZED_VOLATILITY_YZ.value:<18}: {res[PRETTY_PARAMETERS.REALIZED_VOLATILITY_YZ.value]:>12}\n"
             "```\n"
            f"{res[PRETTY_PARAMETERS.STATUS.value]}"
        )
        return res, msg, False
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
#     data, err = bs_greeks_wrapper(inst)
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
    _, msg, is_error = get_greeks(context.args[0].upper())
    if is_error:
        await update.message.reply_text(msg)
        return
    await update.message.reply_text(msg, parse_mode="Markdown")

def get_greeks(inst_name: str) -> tuple[dict, str, bool]:
    """
    /greeks [INSTRUMENT_NAME] - Show option Greeks (Delta, Gamma, Vega, Theta, Rho)
    Example: /greeks BTC-31DEC25-6000-C
    """
    data, err = bs_greeks_wrapper(inst_name)
    if err: return {}, err, True
    g_mkt = data["g_mkt"]
    res = {
        PRETTY_PARAMETERS.INSTRUMENT_NAME.value: inst_name,
        PRETTY_PARAMETERS.DELTA.value: g_mkt['delta'],
        PRETTY_PARAMETERS.GAMMA.value: g_mkt['gamma'],
        PRETTY_PARAMETERS.VEGA.value: g_mkt['vega_per_1pct'],
        PRETTY_PARAMETERS.THETA.value: g_mkt['theta_per_day'],
        PRETTY_PARAMETERS.RHO.value: g_mkt['rho_per_1pct']
    }
    msg = (
        f"*{res[PRETTY_PARAMETERS.INSTRUMENT_NAME.value]} — Greeks (mid→last(fresh)→mark)*\n```\n"
        f"{res[PRETTY_PARAMETERS.DELTA.value]}  : {g_mkt['delta']:.4f}\n"
        f"{res[PRETTY_PARAMETERS.GAMMA.value]}  : {g_mkt['gamma']:.6f}\n"
        f"{res[PRETTY_PARAMETERS.VEGA.value]}   : {g_mkt['vega_per_1pct']:.4f}\n"
        f"{res[PRETTY_PARAMETERS.THETA.value]}  : {g_mkt['theta_per_day']:.4f}\n"
        f"{res[PRETTY_PARAMETERS.RHO.value]}    : {g_mkt['rho_per_1pct']:.4f}\n"
        "```"
    )
    return res, msg, False

# === MAIN ===
def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("price", price))
    app.add_handler(CommandHandler("basis", basis))
    app.add_handler(CommandHandler("option", option))
    app.add_handler(CommandHandler("greeks", greeks))
    app.add_handler(CommandHandler("runsc", runsc))
    app.add_handler(CommandHandler("runsp", runsp))
    app.add_handler(CommandHandler("runbc", runbc))
    app.add_handler(CommandHandler("runbp", runbp))
    app.add_handler(CommandHandler("prob", prob))
    app.add_handler(CommandHandler("misprice", misprice))
    app.add_error_handler(error_handler)
    

    print("Deribit bot running... Ctrl+C to stop.")
    app.run_polling()

if __name__ == "__main__":
    main()
