import requests
import os
from dotenv import load_dotenv
from telegram.ext import Application, CommandHandler

from app.pages.crypto_viewer.deribit import (
    start,
    price,
    get_price,
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

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_TEST_CHAT_ID = os.getenv("TELEGRAM_TEST_CHAT_ID")  # todo: change to list of chat ids if multiple groups

def start_bot() -> Application:
    app = Application.builder().token(TELEGRAM_TOKEN).build()
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

def show_price(base: str) -> list[str] | None:
    """
    Wrapper function to get price information for a given base (BTC or ETH).
    """
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"  # todo: change to list of chat ids if multiple groups
    
    try:
        lines, msg, is_error = get_price(base)
        if is_error:
            raise ValueError(msg)
    
        payload = {
            "chat_id": TELEGRAM_TEST_CHAT_ID,  # todo: change to list of chat ids if multiple groups
            "text": msg,
            "parse_mode": "markdown",
        }
        res = requests.post(url, data=payload, timeout=10)  # todo: change to list of chat ids if multiple groups
        res.raise_for_status()
        return lines
    except Exception as e:
        print(f"Error fetching price for {base} in telegram_utils.show_price: {e}")
        return None
    
if __name__ == "__main__":
    start_bot()
