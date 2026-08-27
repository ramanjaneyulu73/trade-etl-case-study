"""Trade status dashboard: valid / expired / rejected trades from Snowflake."""
import os
from pathlib import Path

import pandas as pd
import plotly.express as px
import snowflake.connector
import streamlit as st
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

st.set_page_config(page_title="Trade ETL Dashboard", layout="wide")


@st.cache_resource
def get_connection():
    return snowflake.connector.connect(
        account=os.environ["SNOWFLAKE_ACCOUNT"],
        user=os.environ["SNOWFLAKE_USER"],
        password=os.environ["SNOWFLAKE_PASSWORD"],
        role=os.environ["SNOWFLAKE_ROLE"],
        warehouse=os.environ["SNOWFLAKE_WAREHOUSE"],
        database=os.environ["SNOWFLAKE_DATABASE"],
        schema="MARTS",
    )


@st.cache_data(ttl=60)
def run_query(sql: str) -> pd.DataFrame:
    conn = get_connection()
    return conn.cursor().execute(sql).fetch_pandas_all()


st.title("Trade ETL Pipeline — Status Dashboard")

valid_df = run_query("select * from fct_valid_trades")
rejected_df = run_query("select * from fct_rejected_trades")

col1, col2, col3, col4 = st.columns(4)
col1.metric("Active trades", int((valid_df["TRADE_STATUS"] == "ACTIVE").sum()))
col2.metric("Expired trades", int((valid_df["TRADE_STATUS"] == "EXPIRED").sum()))
col3.metric("Rejected messages", len(rejected_df))
col4.metric("Total notional (valid)", f"{valid_df['NOTIONAL'].sum():,.0f}")

st.subheader("Trade status breakdown")
status_counts = valid_df["TRADE_STATUS"].value_counts().reset_index()
status_counts.columns = ["status", "count"]
rejected_counts = pd.DataFrame({"status": ["REJECTED"], "count": [len(rejected_df)]})
combined = pd.concat([status_counts, rejected_counts], ignore_index=True)
st.plotly_chart(px.pie(combined, names="status", values="count", hole=0.4), use_container_width=True)

st.subheader("Rejection reasons")
if not rejected_df.empty:
    reason_counts = rejected_df["REJECTION_REASON"].value_counts().reset_index()
    reason_counts.columns = ["reason", "count"]
    st.plotly_chart(px.bar(reason_counts, x="reason", y="count"), use_container_width=True)
else:
    st.info("No rejected trades yet.")

st.subheader("Notional by currency (active trades)")
active_df = valid_df[valid_df["TRADE_STATUS"] == "ACTIVE"]
by_currency = active_df.groupby("CURRENCY")["NOTIONAL"].sum().reset_index()
st.plotly_chart(px.bar(by_currency, x="CURRENCY", y="NOTIONAL"), use_container_width=True)

st.subheader("Recent rejected trades")
st.dataframe(
    rejected_df.sort_values("REJECTED_AT", ascending=False)
    .head(50)[["TRADE_ID", "VERSION", "REJECTION_REASON", "REJECTED_AT", "SOURCE_FILE_NAME"]]
)

st.subheader("Valid trades")
st.dataframe(
    valid_df.sort_values("PROCESSED_AT", ascending=False)
    .head(200)[["TRADE_ID", "VERSION", "TRADE_STATUS", "MATURITY_DATE", "COUNTERPARTY", "NOTIONAL", "CURRENCY"]]
)
