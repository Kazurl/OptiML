from datetime import datetime
import sqlite3

from utils.enums_option import OPTION_MODEL, OPTION_MODEL_ABBR, PARAMETERS

"""
TABLE COLS
id: auto generated id
unique_code: composite identifier where key option parameters encoded directly into ID
             [MODEL_ABBR]_[TYPE_ABBR]_[UNDERLYING]_[DTE]_[STRIKE]_[R]_[SIGMA]_[Q]
timestamp: Query created at
model: option model used
option_type: CALL/ PUT
stock_price: underlying price used
strike_price: strike/ exercise price used
days_to_expiry: expiry window of option used
volatility: sigma used
dividend_yield: dividend used. defaults to 0.0
time_steps: only for binomial model. defaults to NULL
output_price: model generated premium price of option
"""
def init_db(
    db_path: str = "options_calcs.db"
) -> None:
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute(
        '''
        CREATE TABLE IF NOT EXISTS options_calcs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            unique_code TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            model TEXT,
            option_type TEXT,
            stock_price REAL,
            strike_price REAL,
            days_to_expiry INTEGER,
            interest_rate REAL,
            volatility REAL,
            dividend_yield REAL,
            time_steps INTEGER,
            option_price REAL
        )
        '''
    )

    # commit to db and clean up resources
    conn.commit()
    cur.close()
    conn.close()


"""
Helper function to generate unique_code for TABLE 'options_calcs'
"""
def generate_unique_code(
    model: str,
    params: dict
) -> str:
    stock_price = params.get(PARAMETERS.STOCK_PRICE.value, "NA")
    dte = params.get(PARAMETERS.DAYS_TO_EXPIRY.value, 0)
    strike = int(params.get(PARAMETERS.STRIKE_PRICE.value, 0) * 1000)  # std to thousands
    r = params.get(PARAMETERS.INTEREST_RATE.value, 0)
    sigma = params.get(PARAMETERS.VOLATILITY.value, 0.0)
    q = params.get(PARAMETERS.DIVIDEND_YIELD.value, 0.0)
    opt_type = "C" if params.get("option_type", "").lower().startswith("call") else "P"

    if model == OPTION_MODEL.BINOMIAL_MODEL.value:
        model = OPTION_MODEL_ABBR.BINOMIAL_MODEL.value
    elif model == OPTION_MODEL.BLACK_SCHOLES_MODEL.value:
        model = OPTION_MODEL_ABBR.BLACK_SCHOLES_MODEL.value
    else:
        model = OPTION_MODEL_ABBR.SIMPLE_BINOMIAL_MODEL.value

    code = f"{model}_{opt_type}_{stock_price}_{dte}D_{strike}_{r:.4f}_{sigma:.4f}_{q:.4f}"
    return code


"""
Helper function for TABLE 'options_calcs' insertion everytime models are queried
"""
def insert_run_to_db(
    model: str,
    params: dict,
    premium_output: float,
    db_path: str = "options_calcs.db"
) -> None:
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    unique_code = generate_unique_code(model, params)  # generate composite unique_code
    cur.execute(
        '''
        INSERT INTO options_calcs
        (
            unique_code,
            model,
            option_type,
            stock_price,
            strike_price,
            days_to_expiry,
            interest_rate,
            volatility,
            dividend_yield,
            time_steps,
            option_price
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''',
        (
            unique_code,
            model,
            params.get("option_type"),
            params.get(PARAMETERS.STOCK_PRICE.value),
            params.get(PARAMETERS.STRIKE_PRICE.value),
            params.get(PARAMETERS.DAYS_TO_EXPIRY.value),
            params.get(PARAMETERS.INTEREST_RATE.value),
            params.get(PARAMETERS.VOLATILITY.value),
            params.get(PARAMETERS.DIVIDEND_YIELD.value),
            params.get(PARAMETERS.TIME_STEPS.value),
            premium_output
        )
    )

    # commit to db and clean up resources
    conn.commit()
    cur.close()
    conn.close()