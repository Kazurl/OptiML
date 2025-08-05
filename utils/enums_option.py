from enum import Enum

class OPTION_MODEL(Enum):
    BINOMIAL_MODEL = "binomial model"
    BLACK_SCHOLES_MODEL = "black scholes model"
    SIMPLE_BINOMIAL_MODEL = "simple binomial model"

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

    # Only for simple binomial calculation
    UP_FACTOR = "up_factor"
    DOWN_FACTOR = "down_factor"
