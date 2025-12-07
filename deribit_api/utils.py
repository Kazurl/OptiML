import logging
import os

import asyncio
import certifi
import httpx
import requests
import time
from dotenv import load_dotenv

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


async def get_index_price(
        index_name: str,
        cache: dict,
        ttl_seconds: int = 5
    ) -> float | None:
    """
    Fetches the current index price for the given index name.

    Parameters:
        index_name (str): The name of the index to fetch the price for.
        cache (dict): The cache dictionary to use. (_INDEX_CACHE)
        ttl_seconds (int, optional): The time-to-live (TTL) in seconds for the cache. Defaults to 5.

    Returns:
        float | None: The current index price, or None if the request fails.
    """

    v = _cget(cache, index_name, ttl_seconds)
    if v is not None:
        return v
    url = f"{DERIBIT_API_BASE}/public/get_index_price"

    try:
        async with httpx.AsyncClient(verify=certifi.where()) as client:
            res = await client.get(
                    url,
                    params={"index_name": index_name},
                    timeout=10
                )
            res.raise_for_status()
            data = res.json() if isinstance(res, httpx.Response) else await res.json()
            price = data.get("result", {}).get("index_price")
            if price is not None:
                price = float(price)
                _cset(cache, index_name, price)
            return price
    except Exception as e:
        logging.warning(f"get_index_price {index_name} failed: {e}")
    return None


async def _get_deribit_index_usd_first(
        base: str,
        cache: dict,
    ) -> float | None:
    """
    Returns the Deribit index price in USD if available, otherwise USDT/USDC.

    Parameters:
        base (str): The base currency of the index. E.g. "BTC", "ETH"
        cache (dict): The cache dictionary to use. (_INDEX_CACHE)

    Returns:
        float | None: The index price in USD if available, otherwise USDT/USDC, or None if the request fails.
    """

    for q in ("usd", "usdt", "usdc"):
        px = await get_index_price(f"{base.lower()}_{q}", cache=cache)
        if px is not None:
            return float(px)
    return None


async def _pick_min_spot_index(
        base: str,
        cache: dict
    ) -> tuple[float | None, str | None]:
    """
    Picks the lowest available index price for the given base (e.g., BTC, ETH).
    Prefers USD, then USDT, then USDC.

    Parameters:
        base (str): base currency (e.g., BTC, ETH)
        cache (dict): The cache dictionary to use. (_INDEX_CACHE)

    Returns:
        tuple[float | None, str | None]: (price, currency)
        If none found, returns (None, None).
    """

    choices = []
    for ccy in ("usd", "usdt", "usdc"):
        px = await get_index_price(f"{base.lower()}_{ccy}", cache=cache)
        if px:
            choices.append((float(px), ccy.upper()))
    if not choices:
        return None, None
    
    return min(choices, key=lambda x: x[0])


