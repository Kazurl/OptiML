import streamlit as st
import sqlite3
import pandas as pd

def show_database():
    conn = sqlite3.connect("options_calcs.db")
    df = pd.read_sql_query("SELECT * FROM options_calcs ORDER BY timestamp DESC", conn)
    st.dataframe(df)
    conn.close()