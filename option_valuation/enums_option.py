from enum import Enum

class OPTION_MODEL(Enum):
    BINOMIAL_MODEL = "binomial model"
    BLACK_SCHOLES_MODEL = "black scholes model"

class OPTION_TYPE(Enum):
    CALL = "call option"
    PUT = "put option"

class PARAMETERS(Enum):
    STOCK_PRICE = "stock_price"
    STRIKE_PRICE = "strike_price"
    INTEREST_RATE = "interest_rate"
    VOLATILITY = "volatility"
    DAYS_TO_EXPIRY = "days_to_maturity"
    DIVIDEND_YIELD = "dividend_yield"
    TIME_STEPS = "time_steps"
    MAX_END_PRICE = "max_end_price"
    MIN_END_PRICE = "min_end_price"