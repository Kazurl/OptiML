import requests
import pandas as pd
from datetime import datetime, timezone

from deribit_api.options import get_book_summary_by_currency, _get_last_trade_ts_ms, _pick_price_mid_last_mark
from deribit_api.utils import get_index_price

async def test_fetch_deribit_options():
    base = "BTC"
    spot = await get_index_price(f"{base.lower()}_usd", cache={})
    if not spot:
        spot = await get_index_price(f"{base.lower()}_usdt", cache={})
    spot = float(spot)

    # Fetch data
    url = "https://www.deribit.com/api/v2/public/get_instruments?currency=BTC&kind=option&expired=false"
    instruments = requests.get(url).json()['result']

    # Convert to DataFrame for easy processing
    #df = pd.DataFrame(instruments)

    # Current UTC timestamp
    now_ts = int(datetime.now(timezone.utc).timestamp())

    # get book summary for bid, ask, last, mark to get mid_raw
    _, bm = await get_book_summary_by_currency(base, "option", ttl=10)

    # Helper to build row dictionary (you may need to adapt premiums/open interest extraction)
    async def build_row(inst):
        expiry_ts = inst.get('expiration_timestamp', 0) / 1000  # API is ms, convert to seconds
        expiry_dt = datetime.fromtimestamp(expiry_ts, tz=timezone.utc)
        date_str = inst.get("instrument_name").split("-")[1]
        tenor_days = max(0, (expiry_ts - now_ts) // 86400)
        summ = bm.get(inst.get("instrument_name"), {})
        bid = summ.get("bid_price")
        ask = summ.get("ask_price")
        last = summ.get("last_price")
        mark = summ.get("mark_price")
        last_ts = None
        if (not bid or bid <= 0 or not ask or ask <= 0) and last and last > 0:
            last_ts = await _get_last_trade_ts_ms(inst.get("instrument_name"))
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
        return {
            "date": date_str,
            "tenor": tenor_days,
            "strike": inst.get('strike'),
            "premium_usd": float(prem_usd or 0.0),
            "premium_coin": float(prem_coin or 0.0),
            "open_interest": oi,
            "instrument_name": inst.get('instrument_name'),
            "underlying": und,
            "quote_ccy": quote_ccy
        }

    # Sort and group by expiry
    sorted_insts = sorted(instruments, key=lambda x: x['expiration_timestamp'])
    expiry_dict = {}
    for inst in sorted_insts:
        row = await build_row(inst)
        expiry = row['date']
        expiry_dict.setdefault("-".join([row["date"], inst.get("option_type")]), []).append(row)

    # Now expiry_dict is a table/dictionary indexed by expiry date
    import json
    print(json.dumps(expiry_dict, indent=2))

import asyncio
asyncio.run(test_fetch_deribit_options())