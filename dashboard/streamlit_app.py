"""Trade status dashboard: valid / expired / rejected trades from Snowflake."""
import os
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import snowflake.connector
import streamlit as st
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

st.set_page_config(page_title="Trade ETL Dashboard", page_icon="📊", layout="wide")

# Status colors carry real state semantics (active=healthy, expired=neutral
# lifecycle event, rejected=needs attention) rather than arbitrary categorical
# hues, since a trade-status dashboard is exactly the "state of a thing" case
# these are meant for. Muted/critical/good are the validated reference palette
# (see the dataviz skill) - never reused as a generic categorical series color.
COLOR_GOOD = "#0ca30c"      # Active
COLOR_MUTED = "#898781"     # Expired - neutral, not a warning
COLOR_CRITICAL = "#d03b3b"  # Rejected
COLOR_SEQ_1 = "#2a78d6"     # sequential blue - rejection-reason magnitude
COLOR_SEQ_2 = "#eb6834"     # sequential orange - the *second* concurrent
                            # magnitude context takes the next categorical slot
GRIDLINE = "#e1e0d9"
AXIS_TEXT = "#898781"       # theme-invariant per the reference palette

REASON_LABELS = {
    "REJECTED_LOWER_VERSION": "Lower version",
    "SUPERSEDED_SAME_VERSION": "Superseded (same version)",
    "REJECTED_PAST_MATURITY": "Past maturity",
    "REJECTED_INVALID_NOTIONAL": "Invalid notional",
    "REJECTED_INVALID_CURRENCY": "Invalid currency",
    "REJECTED_INVALID_DATES": "Invalid dates",
}

CHART_LAYOUT = {
    "plot_bgcolor": "rgba(0,0,0,0)",
    "paper_bgcolor": "rgba(0,0,0,0)",
    "font": {"family": "system-ui, -apple-system, 'Segoe UI', sans-serif", "color": AXIS_TEXT},
    "margin": {"l": 0, "r": 20, "t": 10, "b": 0},
}


def human_money(value: float) -> str:
    """Compact currency label: 1,284 style precision is noise past a few digits."""
    for unit, divisor in [("B", 1e9), ("M", 1e6), ("K", 1e3)]:
        if abs(value) >= divisor:
            return f"${value / divisor:,.1f}{unit}"
    return f"${value:,.0f}"


def get_secret(key: str) -> str:
    """Local dev reads .env via os.environ; Streamlit Community Cloud has no
    .env file and injects secrets into st.secrets instead."""
    if key in os.environ:
        return os.environ[key]
    return st.secrets[key]


@st.cache_resource
def get_connection():
    return snowflake.connector.connect(
        account=get_secret("SNOWFLAKE_ACCOUNT"),
        user=get_secret("SNOWFLAKE_USER"),
        password=get_secret("SNOWFLAKE_PASSWORD"),
        role=get_secret("SNOWFLAKE_ROLE"),
        warehouse=get_secret("SNOWFLAKE_WAREHOUSE"),
        database=get_secret("SNOWFLAKE_DATABASE"),
        schema="MARTS",
    )


@st.cache_data(ttl=60)
def run_query(sql: str) -> pd.DataFrame:
    conn = get_connection()
    return conn.cursor().execute(sql).fetch_pandas_all()


st.title("Trade ETL Pipeline — Status Dashboard")
st.caption("Live from Snowflake · refreshes every 60s")

valid_df = run_query("select * from fct_valid_trades")
rejected_df = run_query("select * from fct_rejected_trades")

active_count = int((valid_df["TRADE_STATUS"] == "ACTIVE").sum())
expired_count = int((valid_df["TRADE_STATUS"] == "EXPIRED").sum())
rejected_count = len(rejected_df)
total_count = active_count + expired_count + rejected_count

col1, col2, col3, col4 = st.columns(4)
col1.metric("Active trades", f"{active_count:,}")
col2.metric("Expired trades", f"{expired_count:,}")
col3.metric("Rejected messages", f"{rejected_count:,}")
col4.metric("Total notional (valid)", f"${valid_df['NOTIONAL'].sum():,.0f}")

st.subheader("Trade status breakdown")
status_fig = go.Figure()
for label, count, color in [
    ("Active", active_count, COLOR_GOOD),
    ("Expired", expired_count, COLOR_MUTED),
    ("Rejected", rejected_count, COLOR_CRITICAL),
]:
    pct = count / total_count * 100 if total_count else 0
    status_fig.add_trace(go.Bar(
        y=["Trades"], x=[count], name=f"{label} ({pct:.0f}%)", orientation="h",
        marker={"color": color, "line": {"width": 2, "color": "rgba(0,0,0,0)"}},
        text=f"{count:,}" if pct >= 6 else "", textposition="inside", insidetextanchor="middle",
        textfont={"color": "#ffffff"},
        hovertemplate=f"{label}: %{{x:,}} ({pct:.1f}%)<extra></extra>",
    ))
status_fig.update_layout(
    **CHART_LAYOUT,
    barmode="stack",
    height=110,
    showlegend=True,
    legend={
        "orientation": "h", "yanchor": "bottom", "y": 1.05, "x": 0,
        "font": {"color": AXIS_TEXT}, "traceorder": "normal",
    },
    xaxis={"visible": False},
    yaxis={"visible": False},
)
st.plotly_chart(status_fig, use_container_width=True, config={"displayModeBar": False})

col_left, col_right = st.columns(2)

with col_left:
    st.subheader("Rejection reasons")
    if not rejected_df.empty:
        reason_counts = rejected_df["REJECTION_REASON"].value_counts().reset_index()
        reason_counts.columns = ["reason", "count"]
        reason_counts["label"] = reason_counts["reason"].map(REASON_LABELS).fillna(reason_counts["reason"])
        reason_counts = reason_counts.sort_values("count", ascending=True)
        fig = go.Figure(go.Bar(
            x=reason_counts["count"], y=reason_counts["label"], orientation="h",
            marker_color=COLOR_SEQ_1, text=reason_counts["count"].apply(lambda v: f"{v:,}"),
            textposition="outside", cliponaxis=False,
            hovertemplate="%{y}: %{x:,}<extra></extra>",
        ))
        fig.update_layout(
            **CHART_LAYOUT, height=max(180, 40 * len(reason_counts)),
            bargap=0.35,
            xaxis={"showgrid": True, "gridcolor": GRIDLINE, "zeroline": False, "tickformat": ",", "title": None},
            yaxis={"showgrid": False, "title": None},
        )
        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
    else:
        st.info("No rejected trades yet.")

with col_right:
    st.subheader("Notional by currency (active trades)")
    active_df = valid_df[valid_df["TRADE_STATUS"] == "ACTIVE"]
    by_currency = active_df.groupby("CURRENCY")["NOTIONAL"].sum().reset_index()
    by_currency = by_currency.sort_values("NOTIONAL", ascending=False)
    fig = go.Figure(go.Bar(
        x=by_currency["CURRENCY"], y=by_currency["NOTIONAL"],
        marker_color=COLOR_SEQ_2, text=by_currency["NOTIONAL"].apply(human_money),
        textposition="outside", cliponaxis=False,
        hovertemplate="%{x}: %{customdata}<extra></extra>",
        customdata=by_currency["NOTIONAL"].apply(human_money),
    ))
    fig.update_layout(
        **CHART_LAYOUT, height=max(180, 40 * len(reason_counts)) if not rejected_df.empty else 300,
        bargap=0.35,
        xaxis={"showgrid": False, "title": None},
        # Every bar already carries a direct $-abbreviated label; a numeric
        # axis alongside it would need SI units ("G" for billion), which reads
        # as inconsistent next to the finance-style "B" on the bars themselves.
        yaxis={"showgrid": True, "gridcolor": GRIDLINE, "zeroline": False, "showticklabels": False, "title": None},
    )
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

st.subheader("Recent rejected trades")
st.dataframe(
    rejected_df.sort_values("REJECTED_AT", ascending=False)
    .head(50)[["TRADE_ID", "VERSION", "REJECTION_REASON", "REJECTED_AT", "SOURCE_FILE_NAME"]],
    column_config={
        "TRADE_ID": "Trade ID",
        "VERSION": st.column_config.NumberColumn("Version", format="%d"),
        "REJECTION_REASON": "Reason",
        "REJECTED_AT": st.column_config.DatetimeColumn("Rejected at", format="YYYY-MM-DD HH:mm"),
        "SOURCE_FILE_NAME": "Source file",
    },
    hide_index=True,
    use_container_width=True,
)

st.subheader("Valid trades")
st.dataframe(
    valid_df.sort_values("PROCESSED_AT", ascending=False)
    .head(200)[["TRADE_ID", "VERSION", "TRADE_STATUS", "MATURITY_DATE", "COUNTERPARTY", "NOTIONAL", "CURRENCY"]],
    column_config={
        "TRADE_ID": "Trade ID",
        "VERSION": st.column_config.NumberColumn("Version", format="%d"),
        "TRADE_STATUS": "Status",
        "MATURITY_DATE": st.column_config.DateColumn("Maturity date", format="YYYY-MM-DD"),
        "COUNTERPARTY": "Counterparty",
        "NOTIONAL": st.column_config.NumberColumn("Notional", format="$%,.2f"),
        "CURRENCY": "Currency",
    },
    hide_index=True,
    use_container_width=True,
)
