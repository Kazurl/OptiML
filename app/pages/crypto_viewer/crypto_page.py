import os
import streamlit as st
from utils.telegram.telegram_utils import (
    show_price,
)
def load_sidebar_css(css_file_path: str) -> None:
    with open(css_file_path, "r") as f:
        st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)

def show_crypto_page():
    load_sidebar_css(os.path.join("app", "static", "market_sidebar.css"))

    st.title("Crypto Trading Desk")
    st.caption("This section provides tools for cryptocurrency market analysis and trading actions.")
    
    # Example instruments data (in practice, fetch from Deribit API)
    instruments = [
        "BTC-30JUN23-30000-C",
        "BTC-30JUN23-30000-P",
        "ETH-30JUN23-2000-C",
        "ETH-30JUN23-2000-P"
    ]
    base = select_base()
    st.write(f":money_with_wings: Working with {base} Market on Deribit!")

    tab_market, tab_options, tab_vol, tab_trading, tab_telegram = st.tabs(
        [
            "Market Overview",
            "Options Analytics",
            "Volatility/Forecasts",
            "Trading Actions",
            "Telegram Log"
        ]
    )

    with tab_market:
        st.header(f"{base} Market Chart Overview")
        #spot_ref = getspotreference(base, 300)  # e.g. spot reference, 5 min staleness
        #futs = getfuturesinstrumentsbase(base)
        #st.write(f"Spot: {spot_ref}")
        #st.write("Dated Futures")
        #st.write(futs)
        # Optionally, add price/stats table, e.g. priceupdate command

    with tab_options:
        st.header("Options Chain / Greeks")
        #instruments = getoptioninstrumentsbase(base)
        st.write(f"Options available for {base}", instruments)
        # Example command: Option Greeks Lookup
        instrument_name = st.text_input("Enter Option Instrument Name:")
        #if st.button("Get Greeks"):
            #result = greeksupdate(instrument_name)
            #st.write(result)
            #send_command_to_telegram(f"Greeks Query for {instrument_name}")

    with tab_vol:
        st.header("Volatility Surface and Forecasts")
        # Add your function calls to HAR/GARCH forecasts, IV surface, etc.
        # E.g. st.write(forecast results)
        st.write("Feature under development...")
        #send_command_to_telegram("Checked Volatility surface.")

    with tab_trading:
        st.header("Trade Actions")
        action = st.selectbox("Action", ["Buy Call", "Buy Put", "Sell Call", "Sell Put"])
        strike = st.number_input("Strike Price", value=30000)
        expiry = st.text_input("Expiry (YYYY-MM-DD)", "2025-12-31")
        if st.button(f"Execute {action}"):
            cmd = f"{action} @strike={strike} @expiry={expiry}"
            st.success(f"Simulated trade command: {cmd}")
            #send_command_to_telegram(f"Trade Action: {cmd}")

    with tab_telegram:
        st.header("Telegram Log")
        # Show a log of all sent commands/actions (implement log retrieval)
        st.write("Telegram command log displayed here.")

def select_base() -> str:
    base = st.sidebar.selectbox("Select Base", ["BTC", "ETH",], index=0)  # todo: change to dynamic from an exchange
    data = show_price(base)
    if data:
        #st.sidebar.markdown("\n".join(data), unsafe_allow_html=True)
        idx_label, spot, mark, mid, bid, ask, change, high, low, volume, volchange = data
        change_color = "#ef5350" if "-" in str(change) else "#26a69a"

        st.sidebar.markdown(
            f"""
                <div class="compact-table">
                    <div class="compact-header">{idx_label}</div>
                    <span class="compact-subheader">Deribit Market Snapshot </span>
                    <div class="compact-row" style="margin-bottom:0.21rem;">
                        <span class="compact-label">Index (Spot)</span>
                        <span class="compact-mainprice">{spot}</span>
                    </div>
                    <div class="compact-row">
                        <span class="compact-label">Mark</span>
                        <span class="compact-value">{mark}</span>
                    </div>
                    <div class="compact-row">
                        <span class="compact-label">Mid</span>
                        <span class="compact-value">{mid}</span>
                    </div>
                    <div class="compact-row">
                        <span class="compact-label">Bid</span>
                        <span class="compact-value">{bid}</span>
                    </div>
                    <div class="compact-row">
                        <span class="compact-label">Ask</span>
                        <span class="compact-value">{ask}</span>
                    </div>
                    <div class="compact-row">
                        <span class="compact-label">24h Chg</span>
                        <span style=f"font-weight:700; color:{change_color}; font-size:1.05rem; letter-spacing: 0.01em;">{change}</span>
                    </div>
                    <div class="compact-row">
                        <span class="compact-label">High</span>
                        <span class="compact-value">{high}</span>
                    </div>
                    <div class="compact-row">
                        <span class="compact-label">Low</span>
                        <span class="compact-value">{low}</span>
                    </div>
                    <div class="compact-row">
                        <span class="compact-label">Vol (BTC)</span>
                        <span class="compact-value">{volume}</span>
                    </div>
                    <div class="compact-row">
                        <span class="compact-label">Δ 1D Vol</span>
                        <span class="compact-value">{volchange}</span>
                    </div>
                </div>
            """,
            unsafe_allow_html=True
        )
    else:
        st.sidebar.warning("Price data unavailable.")
    return base