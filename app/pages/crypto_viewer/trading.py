import os
from typing import Dict

from dotenv import load_dotenv

from deribit_api.trading import DeribitTrading, DeribitError

# Load environment variables from .env file
load_dotenv()

# Global trading client
trading_client: DeribitTrading = None
pending_trade: Dict = None
DERIBIT


async def connect_live(update, context):
    """
    Connect to the Deribit live account.
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
        trading_client = DeribitTrading(client_id, client_secret, base_url="https://www.deribit.com/api/v2")
        await trading_client.connect()
        if trading_client.connected:
            await update.message.reply_text("Successfully connected to Deribit Live.")
    except DeribitError as e:
        await update.message.reply_text(f"Error connecting to Deribit Live: {e}")
        trading_client = None


async def connect_test(update, context):
    """
    Connect to the Deribit testnet account.
    """
    global trading_client
    if trading_client and trading_client.connected:
        await update.message.reply_text("Already connected. Please /disconnect first.")
        return

    client_id = os.getenv("DERIBIT_TESTNET_CLIENT_ID")
    client_secret = os.getenv("DERIBIT_TESTNET_CLIENT_SECRET")

    if not client_id or not client_secret:
        await update.message.reply_text(
            "Deribit testnet API keys not found. Please set DERIBIT_TESTNET_CLIENT_ID and DERIBIT_TESTNET_CLIENT_SECRET in your .env file."
        )
        return

    try:
        trading_client = DeribitTrading(client_id, client_secret, base_url="https://test.deribit.com/api/v2")
        await trading_client.connect()
        if trading_client.connected:
            await update.message.reply_text("Successfully connected to Deribit Testnet.")
    except DeribitError as e:
        await update.message.reply_text(f"Error connecting to Deribit Testnet: {e}")
        trading_client = None


async def disconnect_deribit(update, context):
    """
    Disconnect from the Deribit account.
    """
    global trading_client
    if not trading_client or not trading_client.connected:
        await update.message.reply_text("Not connected to Deribit.")
        return

    await trading_client.aclose()
    trading_client = None
    await update.message.reply_text("Successfully disconnected from Deribit.")


async def trade(update, context):
    """
    Initiate a trade.
    Format: /trade <buy/sell> <instrument_name> <amount> [price] [type=limit|market] [time_in_force=good_til_cancelled|fill_or_kill|immediate_or_cancel]
    """
    global pending_trade
    if not trading_client or not trading_client.connected:
        await update.message.reply_text("Not connected to Deribit. Please /connect_live or /connect_test first.")
        return

    try:
        side = context.args[0].lower()
        instrument_name = context.args[1]
        amount = float(context.args[2])

        if side not in ["buy", "sell"]:
            await update.message.reply_text("Invalid side. Use 'buy' or 'sell'.")
            return

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

    except (IndexError, ValueError):
        await update.message.reply_text(
            "Invalid command format. Use: /trade <buy/sell> <instrument_name> <amount> [key=value...]"
        )


async def confirm_trade(update, context):
    """
    Confirm and execute the pending trade.
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

