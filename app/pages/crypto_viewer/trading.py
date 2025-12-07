import os
from telegram import Update
from telegram.ext import ContextTypes
from typing import Dict

from dotenv import load_dotenv

from deribit_api.trading import DeribitTrading, DeribitError

# Load environment variables from .env file
load_dotenv()
DERIBIT_API_BASE = os.getenv("DERIBIT_API_BASE")

# Global trading client
trading_client: DeribitTrading = None
pending_trade: Dict = None


async def connect_live(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /connect_live - Connect to the Deribit live account.
    """
    global trading_client
    if trading_client and trading_client.connected:
        await update.message.reply_text("Already connected. Please /disconnect first.")
        return

    client_id = os.getenv("DERIBIT_CLIENT_ID")
    client_secret = os.getenv("DERIBIT_CLIENT_SECRET")

    if not client_id or not client_secret:
        await update.message.reply_text(
            "Deribit live API keys not found. Please set DERIBIT_CLIENT_ID and DERIBIT_CLIENT_SECRET in your .env file."
        )
        return

    try:
        trading_client = DeribitTrading(client_id, client_secret, is_test=False)
        await trading_client.connect()
        if trading_client.connected:
            await update.message.reply_text("Successfully connected to Deribit Live.")
    except DeribitError as e:
        await update.message.reply_text(f"Error connecting to Deribit Live: {e}")
        trading_client = None


async def connect_test(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /connect_test - Connect to the Deribit testnet account.
    """
    global trading_client
    if trading_client and trading_client.connected:
        await update.message.reply_text("Already connected. Please /disconnect first.")
        return

    client_id = os.getenv("DERIBIT_TESTNET_API_CLIENT_ID")
    client_secret = os.getenv("DERIBIT_TESTNET_API_SECRET")

    if not client_id or not client_secret:
        await update.message.reply_text(
            "Deribit testnet API keys not found. Please set DERIBIT_TESTNET_API_CLIENT_ID and DERIBIT_TESTNET_API_SECRET in your .env file."
        )
        return

    try:
        trading_client = DeribitTrading(client_id, client_secret, is_test=True)
        await trading_client.connect()
        if trading_client.connected:
            await update.message.reply_text("Successfully connected to Deribit Testnet.")
    except DeribitError as e:
        await update.message.reply_text(f"Error connecting to Deribit Testnet: {e}")
        trading_client = None


async def disconnect_deribit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /disconnect - Disconnect from the Deribit account.
    """
    global trading_client
    if not trading_client or not trading_client.connected:
        await update.message.reply_text("Not connected to Deribit.")
        return

    await trading_client.aclose()
    trading_client = None
    await update.message.reply_text("Successfully disconnected from Deribit.")


async def trade(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /trade [B|S] [BTC-31DEC25-60000-C] [amount] [price] [type=limit|market] [time_in_force=good_til_cancelled|fill_or_kill|immediate_or_cancel] - Initiate a trade with confirmation.
    """
    global pending_trade
    if not trading_client or not trading_client.connected:
        await update.message.reply_text("Not connected to Deribit. Please /connect_live or /connect_test first.")
        return

    try:
        if not context.args or len(context.args) < 3:
            raise ValueError("Insufficient arguments. Required: [B|S] [BTC-31DEC25-60000-C] [amount]")
        side = context.args[0].upper()
        instrument_name = context.args[1]
        amount = float(context.args[2])

        if side not in ["B", "S"]:
            await update.message.reply_text("Invalid side. Use 'B' or 'S'.")
            return
        side = "buy" if side == "B" else "sell"

        # Process optional arguments
        kwargs = {}
        for arg in context.args[3:]:
            key, value = arg.split('=')
            if key == 'price':
                kwargs[key] = float(value)
            else:
                kwargs[key] = value


        pending_trade = {
            "side": side,
            "instrument_name": instrument_name,
            "amount": amount,
            "kwargs": kwargs,
        }

        confirmation_message = f"""
        Please confirm the following trade on {trading_client.base_url}:
        Side: {side.capitalize()}
        Instrument: {instrument_name}
        Amount: {amount}
        Options: {kwargs}
        
        To confirm, type /confirm_trade
        """
        await update.message.reply_text(confirmation_message)
        
    except DeribitError as e:
        await update.message.reply_text(f"Trade failed: {e}")
    except IndexError:
        await update.message.reply_text(
            "Invalid command format. Use: /trade [B|S] [BTC-31DEC25-60000-C] [amount] [price] [type=limit|market] [time_in_force=good_til_cancelled|fill_or_kill|immediate_or_cancel]"
        )
    except ValueError as e:
        await update.message.reply_text(e)


async def confirm_trade(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /confirm_trade - Confirm and execute the pending trade.
    """
    global pending_trade
    if not pending_trade:
        await update.message.reply_text("No pending trade to confirm.")
        return

    side = pending_trade["side"]
    instrument_name = pending_trade["instrument_name"]
    amount = pending_trade["amount"]
    kwargs = pending_trade["kwargs"]

    try:
        if side == "buy":
            result = await trading_client.buy(instrument_name, amount, **kwargs)
        else:
            result = await trading_client.sell(instrument_name, amount, **kwargs)

        await update.message.reply_text(f"Trade executed successfully: {result}")
    except DeribitError as e:
        await update.message.reply_text(f"Trade failed: {e}")

    pending_trade = None


async def account_summary(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /account_summary [BTC|ETH] [T|F] - Fetch and display account summary.
    """
    if not trading_client or not trading_client.connected:
        await update.message.reply_text("Not connected to Deribit. Please /connect_live or /connect_test first.")
        return

    try:
        currency, extended = "BTC", True
        if context.args and context.args[0].upper() in ["BTC", "ETH"]:
            currency = context.args[0].upper()
        else:
            await update.message.reply_text(f"Compulsory currency argument missing or invalid. Defaulting to BTC.")
        if context.args and len(context.args) > 1:
            extended = context.args[1].upper() == 'T'
        summary = await trading_client.get_account_summary(currency, extended)
        await update.message.reply_text(f"Account Summary:\n{summary}")
    except DeribitError as e:
        await update.message.reply_text(f"Failed to fetch account summary: {e}")