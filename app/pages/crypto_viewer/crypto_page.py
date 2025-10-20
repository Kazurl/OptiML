import os
import pandas as pd
import streamlit as st
import time

from app.utils.cache import init_st_cache
from app.utils.enums_cache import (
    CACHE_KEYS
)
from utils.telegram.telegram_utils import (
    show_all_option_valuations_greeks,
    show_all_runs,
    show_price,
    show_prob,
)
from utils.enums_option import (
    BASE_TYPES, PRETTY_PARAMETERS, PRETTY_RUNS_TYPE,
)
from utils.string_formatter import (
    inst_name_formatter,
)

def load_sidebar_css(css_file_path: str) -> None:
    with open(css_file_path, "r") as f:
        st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)

def show_base_info(data: list) -> str:
    if data:
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

def render_contract_table_with_side_tooltips(
    contracts_df, valuation_df, greeks_df, base
) -> str:
    """
    Main Runs Contracts Table with 'Valuations & Greeks' data tooltips upon hovering of first cell.
    """
    html = '''
    <div class="sticky-table-container">
    <table class="option-table"><thead><tr>
    '''
    # Table headers
    for col in contracts_df.columns:
        html += f'<th>{col}</th>'
    html += '</tr></thead><tbody>'


    for i, row in contracts_df.iterrows():
        inst_name = inst_name_formatter(
            base, row["Date"], "".join(row["Strike"].split(",")), str(row["Type"])[0]
        )
        valuation_row = valuation_df[valuation_df[valuation_df.columns[0]] == inst_name].squeeze() if not valuation_df.empty else None
        greeks_row = greeks_df[greeks_df[greeks_df.columns[0]] == inst_name].squeeze() if not greeks_df.empty else None


        # --- Valuation and Greeks columns ---
        valuation_html = "<div class='valuation-column'><div class='tooltip-title'>Valuation</div>"
        if valuation_row is not None and not valuation_row.empty:
            for k, v in valuation_row[1:].items():
                valuation_html += f"<div class='tooltip-row'>{k}:     <b>{v}</b></div>"
        else:
            valuation_html += "<div class='tooltip-row'>No data</div>"
        valuation_html += "</div>"


        greeks_html = "<div class='greeks-column'><div class='greeks-title'>Greeks</div>"
        if greeks_row is not None and not greeks_row.empty:
            for k, v in greeks_row[1:].items():
                greeks_html += f"<div class='tooltip-row'>{k}:     <b>{v}</b></div>"
        else:
            greeks_html += "<div class='tooltip-row'>No data</div>"
        greeks_html += "</div>"


        tooltip_html = f"<div class='tooltip-popup'>{valuation_html}{greeks_html}</div>"


        # --- Render row, only first cell clickable/hoverable
        html += "<tr>"
        first_cell = True
        for val in row:
            if first_cell:
                html += f"<td class='hover-contract'>{val}{tooltip_html}</td>"
                first_cell = False
            else:
                html += f"<td>{val}</td>"
        html += "</tr>"


    html += '</tbody></table>'
    return html

def render_console_style_telegram_block(label_value_lines: list, title: str):
    # label_value_lines: list of (label, value)
    block = "<div class='console-telegram-block'>"
    block += f"<div class='console-telegram-block-title'>{title} — ITM Probability</div>"
    block += "<pre>"
    for label, value in label_value_lines:
        # Change the padding to desired spacing
        block += f"{label.ljust(18)} : {value}\n"
    block += "</pre></div>"
    return block


def show_crypto_page():
    streamlit_cache = init_st_cache()  # todo: review caching
    load_sidebar_css(os.path.join("app", "static", "market_sidebar.css"))

    st.title("Crypto Trading Desk")
    st.caption("This section provides tools for cryptocurrency market analysis and trading actions.")
    
    # base = streamlit_cache.get_cached(CACHE_KEYS.BASE.value)
    # if not base:
    #     base = st.sidebar.selectbox("Select Base", ["BTC", "ETH",], index=0) # todo: change to dynamic from an exchange
    #     streamlit_cache.set_cache(CACHE_KEYS.BASE.value, base)
    base = st.sidebar.selectbox("Select Base", ["BTC", "ETH",], index=0)
    
    # data = streamlit_cache.get_cached(CACHE_KEYS.PRICE.value)
    # if not data:
    #     data = show_price(base)
    #     streamlit_cache.set_cache(CACHE_KEYS.PRICE.value, data)
    data = show_price(base)
    show_base_info(data)

    st.write(f":money_with_wings: Working with {base} Market on Deribit!")
    # sample data
    # runs = streamlit_cache.get_cached(CACHE_KEYS.RUNS.value)
    # if not runs:
    #     runs = show_all_runs(base)
    #     streamlit_cache.set_cache(CACHE_KEYS.RUNS.value, runs)
    runs = show_all_runs(base)

    tab_market, tab_options, tab_vol, tab_trading, tab_telegram = st.tabs(
        [
            "Market Overview",
            "Options Analytics",
            "Volatility/Forecasts",
            "Trading Actions",
            "Telegram Log"
        ]
    )
    
    # load all runs' options valuations and greeks
    # all_valuations_greeks = streamlit_cache.get_cached(CACHE_KEYS.ALL_VALUATIONS_GREEKS.value)
    # if not all_valuations_greeks:
    #     inst_dict = {}
    #     for run_type, (raw_data, processed_data) in runs.items():
    #         inst_dict[run_type] = []
    #         for cols in raw_data:
    #             # data = [date, tenor, strike, action_symbol, type, premium_usd, premium_coin, open_interest]
    #             # inst_name = "BTC-30DEC22-40000-C" or "ETH-30DEC22-40000-P"
    #             inst_name = inst_name_formatter(base, cols[0], cols[2], cols[4][0])
    #             inst_dict[run_type].append(inst_name)
    #     all_valuations_greeks = show_all_option_valuations_greeks(inst_dict)
    #     streamlit_cache.set_cache(CACHE_KEYS.ALL_VALUATIONS_GREEKS.value, all_valuations_greeks)
    inst_dict = {}
    for run_type, (raw_data, processed_data) in runs.items():
        inst_dict[run_type] = []
        for cols in raw_data:
            # data = [date, tenor, strike, action_symbol, type, premium_usd, premium_coin, open_interest]
            # inst_name = "BTC-30DEC22-40000-C" or "ETH-30DEC22-40000-P"
            inst_name = inst_name_formatter(base, cols[0], cols[2], cols[4][0])
            inst_dict[run_type].append(inst_name)
    all_valuations_greeks = show_all_option_valuations_greeks(inst_dict)

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
        runs_tabs = st.tabs(
            ["Buy Call", "Buy Put", "Sell Call", "Sell Put"]
        )
        # runs_cols, valuation_cols, greeks_cols
        runs_cols = [
            "Date",
            "DTE",
            PRETTY_PARAMETERS.STRIKE_PRICE.value,
            "B/S",
            PRETTY_PARAMETERS.OPTION_TYPE.value,
            "USD",
            base,
            PRETTY_PARAMETERS.OPEN_INTEREST.value
        ]
        valuation_cols = [
            PRETTY_PARAMETERS.INSTRUMENT_NAME.value,
            PRETTY_PARAMETERS.SPOT_PRICE.value,
            PRETTY_PARAMETERS.STRIKE_PRICE.value,
            PRETTY_PARAMETERS.OPTION_TYPE.value,
            PRETTY_PARAMETERS.DAYS_TO_EXPIRY.value,
            PRETTY_PARAMETERS.INTEREST_RATE.value,
            PRETTY_PARAMETERS.OPTION_MID.value+f" ({base})",
            PRETTY_PARAMETERS.OPTION_MID.value+" (USD)",
            PRETTY_PARAMETERS.FAIR_PRICE.value,
            PRETTY_PARAMETERS.PRICE_DIFF.value,
            PRETTY_PARAMETERS.IMPLIED_VOLATILITY.value,
            PRETTY_PARAMETERS.REALIZED_VOLATILITY_YZ.value,
            PRETTY_PARAMETERS.STATUS.value
        ]
        greeks_cols = [
            PRETTY_PARAMETERS.INSTRUMENT_NAME.value,
            PRETTY_PARAMETERS.DELTA.value,
            PRETTY_PARAMETERS.GAMMA.value,
            PRETTY_PARAMETERS.VEGA.value,
            PRETTY_PARAMETERS.THETA.value,
            PRETTY_PARAMETERS.RHO.value
        ]
        # init dfs
        runs_dfs, valuation_dfs, greeks_dfs = {}, {}, {}
        # create dataframes for each run type
        run_types = [
            PRETTY_RUNS_TYPE.BUY_CALL.value,
            PRETTY_RUNS_TYPE.BUY_PUT.value,
            PRETTY_RUNS_TYPE.SELL_CALL.value,
            PRETTY_RUNS_TYPE.SELL_PUT.value
        ]
        for run_type in run_types:
            runs_dfs[run_type] = pd.DataFrame(
                                    runs[run_type][1],
                                    columns=runs_cols
                                ) if runs[run_type] else pd.DataFrame(columns=runs_cols)
            valuation_dfs[run_type] = pd.DataFrame(
                                        all_valuations_greeks[run_type]["valuations"],
                                        columns=valuation_cols
                                    ) if all_valuations_greeks else pd.DataFrame(columns=valuation_cols)
            greeks_dfs[run_type] = pd.DataFrame(
                                        all_valuations_greeks[run_type]["greeks"],
                                        columns=greeks_cols
                                    ) if all_valuations_greeks else pd.DataFrame(columns=greeks_cols)

        for tab, run in zip(runs_tabs, run_types):
            with tab:
                st.subheader(f"{base} {run} — ATM by Expiry")
                # --- Display Option Contracts (Custom Table) ---
                st.markdown(
                    render_contract_table_with_side_tooltips(
                        contracts_df=runs_dfs[run],
                        valuation_df=valuation_dfs[run],
                        greeks_df=greeks_dfs[run],
                        base=base
                    ),
                    unsafe_allow_html=True
                )
                # --- Display Option Contracts (Streamlit DF) ---
                st.dataframe(
                    runs_dfs[run],
                    height=310,
                    hide_index=True
                )
                # --- Display Option Valuations and Greeks ---
                st.subheader("Option Valuations")
                st.dataframe(
                    valuation_dfs[run],
                    height=310,
                    hide_index=True,
                )
                st.subheader("Option Greeks")
                st.dataframe(greeks_dfs[run], height=310, hide_index=True)

    with tab_vol:
        st.header("Volatility Surface and Forecasts")
        vol_tabs = st.tabs(
            ["Buy Call", "Buy Put", "Sell Call", "Sell Put"]
        )
        inst_dfs = {}
        for run_type in run_types:
            inst_dfs[run_type] = pd.DataFrame(
                                    inst_dict[run_type],
                                    columns=["Instrument Name"]
                                ) if inst_dict[run_type] else pd.DataFrame(columns=["Instrument Name"])
        # Function calls to HAR/GARCH forecasts, IV surface, etc.
        for tab, run_type in zip(vol_tabs, run_types):
            with tab:
                inst_table_col, search_col = st.columns([3, 1])
                with inst_table_col:
                    st.dataframe(inst_dfs[run_type], hide_index=True)
                with search_col:
                    selected_inst_name = st.selectbox(
                                            "Select instrument",
                                            inst_dict[run_type],
                                            index=0,
                                            key="selectbox_prob_instrument"
                                        )
                    prob_res = show_prob(selected_inst_name)
                    prob_input = [(k, v) for k, v in prob_res.items()]
                # show prob result of selected instrument
                if prob_input:
                    st.markdown("---")
                    st.text("Instrument Probability")
                    st.markdown(
                        render_console_style_telegram_block(
                            prob_input, title=selected_inst_name
                        ),
                        unsafe_allow_html=True
                    )
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