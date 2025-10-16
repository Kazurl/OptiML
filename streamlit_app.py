import streamlit as st

from app.pages.crypto_viewer.crypto_page import show_crypto_page
from app.pages.equities_viewer.show_equities_page import show_equities_page
from app.pages.option_valuation.show_options_modelling_page import show_options_modelling_page
from db.sqlite.db_utils import init_db

## ----------------------------------------------
# Initialize db
init_db()


## ----------------------------------------------
# Start of UI
st.title("***OptiML***")
st.divider()

# --- Sidebar Navigation ---
pg = st.navigation(
    [
        st.Page(show_options_modelling_page, title="Options Valuation"),
        st.Page(show_equities_page, title="Equities Trading"),
        st.Page(show_crypto_page, title="Cryptocurrency Trading"),
    ]
)
pg.run()