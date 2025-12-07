import streamlit as st
import time

# todo: review caching

TTL = 3*60*60

class CacheObj:
    def __init__(self, data, timestamp) -> None:
        self.data, self.timestamp = data, timestamp

# class StreamlitCache:
#     def __init__(self, ttl: int = TTL) -> None:
#         self.ttl = ttl
#         self.cache = {}
    
#     def get_cached(self, key: str):
#         if key not in self.cache:
#             return None
#         cached_obj = self.cache[key]
#         if time.time() - cached_obj.timestamp <= self.ttl:
#             return cached_obj.data
#         return None
    
#     def set_cache(self, key, data) -> None:
#         self.cache[key] = CacheObj(data, time.time())
    
#     def reset_cache(self) -> None:
#         self.cache = {}

class StreamlitCache:
    def __init__(self, ttl: int = TTL) -> None:
        self._OPT_CACHE = {}          # key: base -> {t: ts, data: [...]}
        self._BOOK_CACHE = {}         # key: (base, kind) -> {t: ts, data: [...]}
        self._INDEX_CACHE = {}        # key: index_name -> {t: ts, price: float}
        self._RFR_CACHE = {"t": 0.0, "val": None}  # cache RFR to avoid noisy refetches

def init_st_cache() -> StreamlitCache:
    if "cache" not in st.session_state:
        st.session_state["cache"] = StreamlitCache()
    cache = st.session_state["cache"]
    return cache