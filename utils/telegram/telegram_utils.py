import requests
import os
from dotenv import load_dotenv
from telegram.ext import Application, CommandHandler

from app.pages.crypto_viewer.deribit import (
    start,
    price,
    get_greeks,
    get_price,
    get_option,
    get_prob,
    _get_all_runs,
    basis,
    option,
    greeks,
    runsc,
    runsp,
    runbc,
    runbp,
    prob,
    misprice,
    error_handler
)
from utils.enums_option import (
    PRETTY_RUNS_TYPE,
)

""" todo: delete when done
export PYTHONPATH=$(pwd)
python utils/telegram/telegram_utils.py
"""

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_TEST_CHAT_ID = os.getenv("TELEGRAM_TEST_CHAT_ID")  # todo: change to list of chat ids if multiple groups
TELEGRAM_BOT_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"  # todo: change to list of chat ids if multiple groups

def start_bot() -> Application:
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
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

def show_all_option_valuations_greeks(inst_dict: dict[list[str]]) -> dict | None:
    """
    Wrapper function to get option valuations and greeks for all given instruments for each of the 4 runs (sell call, sell put, buy call, buy put).
    Returns a dict with keys as run types and values as:
        {
            "valuations": list of pretty_parameters [inst_name, spot_price, strike_price, option_type, days_to_expiry, interest_rate, option_mid (coin), option_mid (usd), fair_price, price_diff, implied_volatility, realized_volatility_yz, status],

            "greeks": list of pretty_parameters [inst_name, delta, gamma, vega, theta, rho]
        }
    """
    try:
        res = {}
        for run_type, inst_list in inst_dict.items():
            valuations, greeks = [], []
            print(f"{run_type}: {inst_list}")  # todo: remove when done
            for inst_name in inst_list:
                # get the valuation and greeks data for this instrument
                val_raw_data, val_proc_data, _, _ = get_option(inst_name)
                greeks_raw_data, greeks_proc_data, _, _ = get_greeks(inst_name)

                # add to respective row
                valuations.append(val_proc_data.values() if val_proc_data else ["N/A"] * 13)
                greeks.append(greeks_proc_data.values() if greeks_proc_data else ["N/A"] * 6)
            res[run_type] = {"valuations": valuations, "greeks": greeks}
        return res
    except Exception as e:
        print(f"Error fetching option valuations and greeks for {inst_name} in telegram_utils.show_all_option_valuations_greeks: {e}")
        return None
 
def show_all_runs(base: str) -> dict | None:
    """
    Wrapper function to get all 4 run types (sell call, sell put, buy call, buy put) for the given base (BTC or ETH).
    Returns dict of {run_type: raw and processed data list}
    """
    try:
        runs = _get_all_runs(base)
        err_flag = False
        for run_type, (raw_data, processed_data, msg, is_error) in runs.items():
            if is_error: err_flag = True
            # send to telegram
            payload = {
                "chat_id": TELEGRAM_TEST_CHAT_ID,  # todo: change to list of chat ids if multiple groups
                "text": msg,
                "parse_mode": "markdown",
            }
            res = requests.post(TELEGRAM_BOT_URL, data=payload, timeout=10)  # todo: change to list of chat ids if multiple groups
            res.raise_for_status()
        # raise error if any
        if err_flag:
            raise ValueError("One or more errors occurred while fetching runs.")
        return {k: v[:2] for k, v in runs.items()}
    except Exception as e:
        print(f"Error fetching all runs for {base} in telegram_utils.show_all_runs: {e}")
        return {k: v[:2] for k, v in runs.items()}

def show_greeks(inst_name: str) -> dict | None:
    """
    Wrapper function to get option greeks for a given instrument name.
    """
    try:
        data, msg, is_error = get_greeks(inst_name)
        if is_error:
            raise ValueError(msg)
        
        # send to telegram
        payload = {
            "chat_id": TELEGRAM_TEST_CHAT_ID,  # todo: change to list of chat ids if multiple groups
            "text": msg,
            "parse_mode": "markdown",
        }
        res = requests.post(TELEGRAM_BOT_URL, data=payload, timeout=10)  # todo: change to list of chat ids if multiple groups
        res.raise_for_status()
        return data
    except Exception as e:
        print(f"Error fetching option greeks for {inst_name} in telegram_utils.show_greeks: {e}")
        return None

def show_option(inst_name: str) -> dict | None:
    """
    Wrapper function to get option greeks for a given instrument name.
    """
    try:
        data, msg, is_error = get_option(inst_name)
        if is_error:
            raise ValueError(msg)
        
        # send to telegram
        payload = {
            "chat_id": TELEGRAM_TEST_CHAT_ID,  # todo: change to list of chat ids if multiple groups
            "text": msg,
            "parse_mode": "markdown",
        }
        res = requests.post(TELEGRAM_BOT_URL, data=payload, timeout=10)  # todo: change to list of chat ids if multiple groups
        res.raise_for_status()
        return data
    except Exception as e:
        print(f"Error fetching option greeks for {inst_name} in telegram_utils.show_option: {e}")
        return None

def show_price(base: str) -> list[str] | None:
    """
    Wrapper function to get price information for a given base (BTC or ETH).
    """
    try:
        data, msg, is_error = get_price(base)
        if is_error:
            raise ValueError(msg)
    
        payload = {
            "chat_id": TELEGRAM_TEST_CHAT_ID,  # todo: change to list of chat ids if multiple groups
            "text": msg,
            "parse_mode": "markdown",
        }
        res = requests.post(TELEGRAM_BOT_URL, data=payload, timeout=10)  # todo: change to list of chat ids if multiple groups
        res.raise_for_status()
        return data
    except Exception as e:
        print(f"Error fetching price for {base} in telegram_utils.show_price: {e}")
        return None
    
def show_prob(inst_name: str) -> dict | None:
    try:
        raw_data, processed_data, msg, is_error = get_prob(inst_name)
        if is_error:
            raise ValueError(msg)
        
        payload = {
            "chat_id": TELEGRAM_TEST_CHAT_ID,  # todo: change to list of chat ids if multiple groups
            "text": msg,
            "parse_mode": "markdown"
        }
        res = requests.post(TELEGRAM_BOT_URL, data=payload, timeout=10)  # todo: change to list of chat ids if multiple groups
        res.raise_for_status()
        return processed_data
    except Exception as e:
        print(f"Error fetching price for {inst_name} in telegram_utils.show_price: {e}")
        return None
    
if __name__ == "__main__":
    start_bot()
