"""
Check API references at: "https://docs.alpaca.markets/reference/stockbars"
Scroll through the sidebar for various market data api

For Historical and live data on stocks, crypto, options:
alpaca.data.historical

For realtime (live) data streaming:
alpaca.data.live

For specifc data (bars, trades, quotes):
alpaca.data.requests
alpaca.data.timeframe
    - to specify "1Min", "1Hour", "1Day"
"""
### NOTE: Only data since Feb'24 on Alpaca API###

from dotenv import load_dotenv
import os
import requests

from alpaca.data import OptionHistoricalDataClient
from alpaca.data.requests import (
    OptionBarsRequest,
    OptionChainRequest,
)
from alpaca.data.timeframe import TimeFrame
from alpaca.trading.enums import ContractType
import datetime

from alpaca_api.stocks import get_recent_stock_prices, get_single_current_price
from utils.common_formulas import annualized_volatility, price_sampling_adjustment
from utils.enums_option import OPTION_TYPE
from utils.enums_market import SAMPLING_FREQ
from utils.common_formulas import BS_brent_implied_volatility, get_risk_free_rate

load_dotenv()


"""
Convert Alpaca OCC standard option symbols to its individual components
[underlying][YYMMDD][C/P][strike-price * 1000]

E.g. OCC symbol: AAPL250829C00170000
     Components: [AAPL][250829][C][00170000]
"""
def parse_occ_symbol(symbol):
    underlying = symbol[:symbol.find('2')]  # crude split
    year = 2000 + int(symbol[len(underlying):len(underlying)+2])
    month = int(symbol[len(underlying)+2:len(underlying)+4])
    day = int(symbol[len(underlying)+4:len(underlying)+6])
    option_type = symbol[len(underlying)+6]
    strike = int(symbol[len(underlying)+7:]) / 1000
    return {
        "underlying": underlying,
        "expiration_date": datetime.date(year, month, day),
        "type": "CALL" if option_type == "C" else "PUT",
        "strike_price": strike
    }



"""
To obtain Implied Volatility with three layers of flow (Highest -> Lowest priorities)

1. Pulling Real Option Contract Implied Volatility direct from option_chain snapshot
    - same underlying asset
    - similar expiration date (<= specified expiry window)
    - similar strike range
2. BS-based root-finding 
    - if snapshot IV returns None
    - but market option price and underlying price still available
3. Historical volatility fallback
    - when 1 & 2 fail, IV is implied from historical prices via annualized vol
"""
def get_specific_contract_IV(
        symbol: str,  # i.e "AAPL"
        option_type: str,  # i.e "call option"/ "put option"
        X: float,  # exact strike price of contract
        expiry_start: datetime.date,  # range of acceptable expiry
        expiry_end: datetime.date,
        expiry_window: int,  # contract's DAYS_TO_EXPIRY 
        sampling_freq: str = SAMPLING_FREQ.DAILY.value,
        timeframe: TimeFrame = TimeFrame.Day,
        r: float = None  # risk free rate
) -> float:
    option_type = ContractType.CALL if option_type == OPTION_TYPE.CALL.value else ContractType.PUT
    start = expiry_start.strftime("%Y-%m-%d")
    end = expiry_end.strftime("%Y-%m-%d")
    try:
        client = OptionHistoricalDataClient(
             os.getenv("ALPACA_API_KEY"),
             os.getenv("ALPACA_API_SECRET")
        )
        
        # Find contract symbol matching strike and expiry exactly
        chain_req = OptionChainRequest(
            underlying_symbol=symbol,
            expiration_date_gte=start,
            expiration_date_lte=end,
            type=option_type,
            strike_price_gte=X,
            strike_price_lte=X,
            limit=10,
            feed="indicative"  # free plan
        )
        option_chain = client.get_option_chain(chain_req)
        occ_symbol = None
        for occ_symbol, snapshot in option_chain.items():
            occ_data = parse_occ_symbol(occ_symbol)

            if (
                occ_data["strike_price"] == X and
                expiry_start <= occ_data["expiration_date"] <= expiry_end and
                occ_data["type"] == ("CALL" if option_type == ContractType.CALL else "PUT")
            ):
                if snapshot.implied_volatility: 
                    return snapshot.implied_volatility

                # Attempt Fallback 1 - BS_brent
                option_price = None
                if (
                    snapshot.latest_quote and
                    snapshot.latest_quote.ask_price and
                    snapshot.latest_quote.bid_price
                ):
                    option_price = (snapshot.latest_quote.ask_price - snapshot.latest_quote.bid_price)/2
                elif snapshot.latest_trade and snapshot.latest_trade.price:
                    option_price = snapshot.latest_trade.price
                
                if option_price:
                    T=(occ_data["expiration_date"]-datetime.date.today()).days
                    if not r:
                        r = get_risk_free_rate(T/365.0)
                    BS_iv = BS_brent_implied_volatility(
                        option_price=option_price,
                        S=float(get_single_current_price(symbol, expiry_start, expiry_end)),
                        X=X,
                        T=T,
                        r=r,  # todo: change to dynamic
                        option_type=(OPTION_TYPE.CALL.value if option_type == ContractType.CALL else OPTION_TYPE.PUT.value)
                    )
                    if BS_iv:
                        return BS_iv
        
        # Attempt Fallback 2 - IV based on historical stock prices
        today = datetime.date.today()
        prices = get_recent_stock_prices(symbol, today-datetime.timedelta(days=expiry_window), today)
        adjusted_prices = price_sampling_adjustment(prices, sampling_freq)
        # calculate our own volatility
        fallback_vol = annualized_volatility(adjusted_prices, sampling_freq)
        
        return fallback_vol
    except Exception as e:
            raise Exception(f"Error fetching data for ticker {symbol}: {str(e)}")