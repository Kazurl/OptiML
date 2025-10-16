from enum import Enum

class OPTION_MODEL(Enum):
    BINOMIAL_MODEL = "binomial model"
    BLACK_SCHOLES_MODEL = "black scholes model"
    SIMPLE_BINOMIAL_MODEL = "simple binomial model"


class OPTION_MODEL_ABBR(Enum):
    BINOMIAL_MODEL = "BM"
    BLACK_SCHOLES_MODEL = "BSM"
    SIMPLE_BINOMIAL_MODEL = "SBM"


class OPTION_TYPE(Enum):
    CALL = "call option"
    PUT = "put option"


class PARAMETERS(Enum):
    STOCK_PRICE = "stock_price"
    STRIKE_PRICE = "strike_price"
    INTEREST_RATE = "interest_rate"
    VOLATILITY = "volatility"
    DAYS_TO_EXPIRY = "days_to_expiry"
    DIVIDEND_YIELD = "dividend_yield"
    TIME_STEPS = "time_steps"


class PRETTY_OPTION_TYPE(Enum):
    CALL = "Call"
    PUT = "Put"

class PRETTY_PARAMETERS(Enum):
    INSTRUMENT_NAME = "Instrument Name"
    OPTION_TYPE = "Type"
    STOCK_PRICE = "Stock Price"
    SPOT_PRICE = "Spot"
    STRIKE_PRICE = "Strike"
    INTEREST_RATE = "Risk-Free r"
    REALIZED_VOLATILITY = "Realized Vol"
    REALIZED_VOLATILITY_YZ = "Realized Vol (YZ)"
    IMPLIED_VOLATILITY = "Market IV"
    DAYS_TO_EXPIRY = "Expiry (days)"
    DIVIDEND_YIELD = "Dividend Yield"
    TIME_STEPS = "Time Steps (N)"
    OPTION_MID = "Option Mid"
    FAIR_PRICE = "Fair Price"
    PRICE_DIFF = "Price Diff"
    DELTA = "Delta"
    GAMMA = "Gamma"
    THETA = "Theta"
    VEGA = "Vega"
    RHO = "Rho"
    STATUS = "Status"

class PRETTY_RUNS_TYPE(Enum):
    BUY_CALL = "Buy Call"
    BUY_PUT = "Buy Put"
    SELL_CALL = "Sell Call"
    SELL_PUT = "Sell Put"