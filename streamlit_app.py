import textwrap

import altair as alt
import pandas as pd
import streamlit as st

from src.risk_model.data_loader import data_signature
from src.risk_model.kpis import KPI_NOTES, KPI_SPECS, monthly_kpis
from src.risk_model.opportunity import missing_prices, opportunity_loss
from src.risk_model.pipeline import load_all
from src.risk_model.risk import risk_matrix, risk_table

st.set_page_config(page_title="Plant risk model", page_icon=":material/bolt:", layout="wide")

PRICE_BASIS = {"BPP": "bpp_rp_kwh", "Selling price": "selling_price_rp_kwh"}
CLASS_LABEL = {"risk": "Risk", "loss_event": "Loss event", "excluded": "Excluded"}


# `sig` changes whenever a file in data/raw is added or edited, so new data (a longer
# Pricing.csv, another year) is picked up on the next rerun without restarting the app.
@st.cache_data(show_spinner="Loading plant data...", max_entries=2)
def get_data(sig):
    return load_all()


@st.cache_data(show_spinner=False, max_entries=8)
def get_priced(sig, basis, manual):
    d = get_data(sig)
    return opportunity_loss(d["failures"], d["pricing"], basis, manual)


def rp_m(x):
    return f"{x / 1e6:,.0f}"


sig = data_signature()
data = get_data(sig)
units = sorted(data["failures"]["unit"].unique())
years = sorted(data["failures"]["timestamp_start"].dt.year.unique())

# Sidebar: every input that changes the numbers lives here.
with st.sidebar:
    st.header("Settings")
    sel_units = st.pills("Units", units, selection_mode="multi", default=units)
    sel_years = st.pills("Years", years, selection_mode="multi", default=years)
    classes = st.pills("Event classes", list(CLASS_LABEL.values()), selection_mode="multi", default=["Risk", "Loss event"],
                       help="Risk: FD.MP, SF and trips with other statuses. Loss event: FO, MO, FD, MD, PD, FD.SYS "
                            "(candidates to become risk). Excluded: NC, RS, PO, PE, SHD, SUD.")
    st.subheader("Price of lost energy")
    price_mode = st.segmented_control("Price", ["BPP", "Selling price", "Manual"], default="BPP",
                                      label_visibility="collapsed")
    manual = None
    if price_mode == "Manual":
        manual = st.number_input("Rp per kWh", min_value=0.0, value=900.0, step=10.0,
                                 help="Applied to every month and unit.")
    else:
        st.caption("Priced at the month the energy was lost, per unit.")
    group = st.segmented_control("Rank by", ["System", "Component"], default="System")

st.title("Plant operational risk model")
if not sel_units or not sel_years or not classes:
    st.info("Select at least one unit, year and event class.", icon=":material/info:")
    st.stop()

priced_all = get_priced(sig, PRICE_BASIS.get(price_mode, "bpp_rp_kwh"), manual)
inv = {v: k for k, v in CLASS_LABEL.items()}
scoped = priced_all[priced_all["unit"].isin(sel_units) & priced_all["month"].dt.year.isin(sel_years)]
priced = scoped[scoped["event_class"].isin([inv[c] for c in classes])]
gaps = missing_prices(scoped) if price_mode != "Manual" else []
for unit, months in (gaps.items() if len(gaps) else []):
    st.warning(f"{unit}: no price in Pricing.csv for {', '.join(months)}. Those losses are not counted. "
               "Add the months to data/raw/Pricing.csv, or use a manual price.", icon=":material/warning:")
if priced.empty:
    st.warning("No events match these settings.", icon=":material/warning:")
    st.stop()

by = ["unit", "system"] + (["component"] if group == "Component" else [])
table = risk_table(priced, data["business"], by=by)
events = priced.drop_duplicates("event_idx")

with st.container(horizontal=True):
    st.metric("Events", f"{len(events):,}", border=True)
    st.metric("Lost energy (MWh)", f"{priced['lost_mwh'].sum():,.0f}", border=True)
    st.metric("Opportunity loss (Rp million)", rp_m(priced["opportunity_loss_rp"].sum()), border=True)
    st.metric("Downtime (hours)", f"{events['failure_duration_hours'].sum():,.0f}", border=True)

tab_rank, tab_matrix, tab_trend, tab_events, tab_quality, tab_kpi = st.tabs(
    ["Ranking", "Risk matrix", "Monthly loss", "Events", "Data checks", "KPI"])

RANK_STATUS = data["cfg"]["ranking_statuses"]
RANK_COLS = {
    "events": st.column_config.NumberColumn("Events"),
    "downtime_hours": st.column_config.NumberColumn("Downtime (h)", format="%.0f"),
    "mean_repair_hours": st.column_config.NumberColumn("Mean repair (h)", format="%.1f"),
    "lost_mwh": st.column_config.NumberColumn("Lost MWh", format="%,.0f"),
    "opportunity_loss_rp": st.column_config.NumberColumn("Opportunity loss (Rp)", format="%,.0f"),
    "events_per_year": st.column_config.NumberColumn("Events/yr", format="%.1f"),
    "mtbf_hours": st.column_config.NumberColumn("MTBF (h)", format="%.0f"),
    "mean_loss_per_event_rp": st.column_config.NumberColumn("Mean loss/event (Rp)", format="%,.0f"),
    "expected_annual_loss_rp": st.column_config.NumberColumn("Expected annual loss (Rp)", format="%,.0f"),
    "expected_annual_loss_mwh": st.column_config.NumberColumn("Expected annual loss (MWh)", format="%,.0f"),
    "likelihood": st.column_config.NumberColumn("L (1-5)"),
    "consequence": st.column_config.NumberColumn("C (1-5)"),
    "risk_score": st.column_config.NumberColumn("Score"),
    "risk_band": st.column_config.TextColumn("Band"),
}


def pareto_table(events):
    """Loss output and event count per cause code ("Cause Code ID & Name - Component - System"),
    largest first, with the running share of the total. Blank codes stay "Unclassified"."""
    t = (events.assign(failure_mode=events["failure_cause_code"].fillna("Unclassified"))
         .groupby("failure_mode").agg(loss_output_mwh=("lost_mwh", "sum"), frequency=("event_idx", "nunique"))
         .sort_values("loss_output_mwh", ascending=False).reset_index())
    t["cumulative_pct"] = t["loss_output_mwh"].cumsum() / t["loss_output_mwh"].sum() * 100
    return t


def _wrap_label(text, width, max_lines=8):
    """Wrap onto lines of `width` characters; keep the first `max_lines` and mark the cut with an ellipsis."""
    lines = textwrap.wrap(text, width, break_long_words=False)
    if len(lines) > max_lines:
        lines = lines[:max_lines - 1] + [lines[max_lines - 1] + "..."]
    return "\n".join(lines)


def pareto_chart(t, top=10):
    """Bars of loss output per failure mode, with the cumulative share as a line.
    X labels are wrapped onto several lines (Vega draws "\n" as a line break)."""
    d = t.head(top).assign(cumulative_share=lambda x: x["cumulative_pct"] / 100)
    wrap = max(8, min(18, 100 // len(d)))  # fewer bars leave room for wider labels
    d["label"] = d["failure_mode"].map(lambda m: _wrap_label(m, wrap))
    x = alt.X("label:N", sort=None, title="Failure mode",
              axis=alt.Axis(labelAngle=0, labelLimit=0, labelOverlap=False, labelLineHeight=11, labelFontSize=13, labelAlign="center",
                            labelExpr="split(datum.label, '\\n')"))
    bars = alt.Chart(d).mark_bar().encode(
        x=x, y=alt.Y("loss_output_mwh:Q", title="Loss output (MWh)"),
        tooltip=["failure_mode", alt.Tooltip("loss_output_mwh:Q", title="Loss output (MWh)", format=",.0f"),
                 alt.Tooltip("cumulative_share:Q", title="Cumulative", format=".0%"),
                 alt.Tooltip("frequency:Q", title="Events")])
    line = alt.Chart(d).mark_line(point=True, color="orange").encode(
        x=x, y=alt.Y("cumulative_share:Q", title="Cumulative share", axis=alt.Axis(format="%"),
                     scale=alt.Scale(domain=[0, 1])))
    return alt.layer(bars, line).resolve_scale(y="independent")


def expected_loss_chart(df, value, title, selected):
    """Expected annual loss per status; the status chosen in the dropdown is highlighted."""
    return alt.Chart(df).mark_bar().encode(
        x=alt.X("unit_status:N", sort=list(RANK_STATUS), title=None, axis=alt.Axis(labelAngle=0)),
        y=alt.Y(f"{value}:Q", title=title),
        opacity=alt.condition(alt.datum.unit_status == selected, alt.value(1), alt.value(0.35)),
        tooltip=["unit_status", alt.Tooltip(f"{value}:Q", title=title, format=",.0f")])


MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def kpi_chart(k, col, label, zero):
    """One KPI over the months Jan-Dec, one line per selected year."""
    return alt.Chart(k).mark_line(point=True).encode(
        x=alt.X("month_name:N", sort=MONTH_NAMES, title="Month", axis=alt.Axis(labelAngle=0)),
        y=alt.Y(f"{col}:Q", title=label, scale=alt.Scale(zero=zero)),
        color=alt.Color("year:N", title="Year"),
        tooltip=["year", "month_name", alt.Tooltip(f"{col}:Q", title=label, format=",.2f")])


with tab_rank:
    status = st.selectbox("Status", list(RANK_STATUS), format_func=lambda s: f"{s} - {RANK_STATUS[s]}")
    chosen = scoped[scoped["unit_status"] == status]
    if chosen.empty:
        st.info(f"No {status} events for the selected units and years.", icon=":material/info:")
    else:
        rt = risk_table(chosen, data["business"], by=by)
        with st.container(horizontal=True):
            st.metric("Expected annual loss (Rp million)", rp_m(rt["expected_annual_loss_rp"].sum()), border=True)
            st.metric("Expected annual loss (MWh)", f"{rt['expected_annual_loss_mwh'].sum():,.0f}", border=True)
            st.metric("Events", f"{int(rt['events'].sum()):,}", border=True)
        pt = pareto_table(chosen)
        by_status = (risk_table(scoped[scoped["unit_status"].isin(RANK_STATUS)], data["business"],
                                by=["unit", "unit_status"])
                     .groupby("unit_status", as_index=False)[["expected_annual_loss_rp", "expected_annual_loss_mwh"]].sum()
                     .assign(loss_m=lambda t: t["expected_annual_loss_rp"] / 1e6))
        left, right = st.columns([1, 3])
        with left.container(border=True):
            st.subheader("Expected loss")
            st.altair_chart(expected_loss_chart(by_status, "loss_m", "Rp million per year", status), height=220,
                            alt="Expected annual loss in Rp million for FO, MO, FD and MD, selected status highlighted")
            st.altair_chart(expected_loss_chart(by_status, "expected_annual_loss_mwh", "MWh per year", status),
                            height=220, alt="Expected annual loss in MWh for FO, MO, FD and MD, selected status highlighted")
        with right.container(border=True):
            st.subheader("Pareto of loss output")
            st.altair_chart(pareto_chart(pt),
                            alt=f"Pareto chart of loss output in MWh by failure mode for {status} events, top 10")
        with st.container(border=True):
            st.subheader("Pareto loss output")
            st.dataframe(
                pt[["failure_mode", "loss_output_mwh", "cumulative_pct", "frequency"]], hide_index=True,
                alt=f"Loss output, cumulative share and frequency by failure mode for {status} events",
                column_config={
                    "failure_mode": st.column_config.TextColumn("Failure Mode", width="large"),
                    "loss_output_mwh": st.column_config.NumberColumn("Loss Output (MWh)", format="%,.1f"),
                    "cumulative_pct": st.column_config.NumberColumn("Cumulative (%)", format="%.1f"),
                    "frequency": st.column_config.NumberColumn("Frequency (Event)"),
                })
        with st.container(border=True):
            st.subheader("Risk table")
            st.dataframe(rt.drop(columns=["period_hours", "service_hours"]), hide_index=True,
                         alt=f"Risk table for {status} events", column_config=RANK_COLS)
        st.caption("Likelihood and consequence levels are ranks among the groups shown (1 = lowest fifth, "
                   "5 = highest fifth), so they change with the filters. The Ranking tab ignores the "
                   "Event classes filter and always shows the selected status.")

with tab_matrix:
    with st.container(border=True):
        st.subheader("Groups by likelihood and consequence")
        st.dataframe(risk_matrix(table).rename_axis(index="Likelihood", columns="Consequence")
                     .style.background_gradient(cmap="Reds", vmin=0), alt="Likelihood by consequence matrix")
    st.caption("Count of groups per cell. Likelihood: events per year. Consequence: mean loss per event.")

with tab_trend:
    trend_years = [int(y) for y in years]  # years with recorded events (an event can spill a sliver into the next year)
    trend_year = st.selectbox("Year", trend_years, index=len(trend_years) - 1, key="trend_year")
    mon = priced_all[priced_all["unit"].isin(sel_units) & priced_all["event_class"].isin([inv[c] for c in classes])
                     & (priced_all["month"].dt.year == trend_year)]
    grid = pd.MultiIndex.from_product([sorted(sel_units), range(1, 13)], names=["unit", "m"])
    by_unit = (mon.assign(m=mon["month"].dt.month).groupby(["unit", "m"])["opportunity_loss_rp"].sum()
               .reindex(grid, fill_value=0).div(1e6).rename("loss_m").reset_index())
    by_unit["month_name"] = by_unit["m"].map(lambda m: MONTH_NAMES[m - 1])
    total = by_unit.groupby(["m", "month_name"], as_index=False)["loss_m"].sum()
    x = alt.X("month_name:N", sort=MONTH_NAMES, title="Month", axis=alt.Axis(labelAngle=0))
    bars = alt.Chart(by_unit).mark_bar().encode(
        x=x, xOffset=alt.XOffset("unit:N"), y=alt.Y("loss_m:Q", title="Opportunity loss (Rp million)"),
        color=alt.Color("unit:N", title="Unit"),
        tooltip=["unit", "month_name", alt.Tooltip("loss_m:Q", title="Rp million", format=",.0f")])
    line = alt.Chart(total).mark_line(point=True, color="orange").encode(
        x=x, y="loss_m:Q",
        tooltip=["month_name", alt.Tooltip("loss_m:Q", title="Total of units (Rp million)", format=",.0f")])
    with st.container(border=True):
        st.subheader(f"Opportunity loss by month, {trend_year} (Rp million)")
        st.altair_chart(alt.layer(bars, line),
                        alt=f"Grouped bars of opportunity loss per unit by month in {trend_year}, with the monthly total as a line")
        st.caption("Bars: each unit's loss. Orange line: sum of the units for the month. "
                   "Follows the sidebar Units, Event classes and price settings; the year is chosen here.")

with tab_events:
    show = events[["timestamp_start", "unit", "unit_status", "event_class", "failure_impact", "system",
                   "component", "root_cause_failure_analysis", "failure_duration_hours", "loss_output_mwh"]]
    st.dataframe(show, hide_index=True, alt="Failure events",
                 column_config={"failure_duration_hours": st.column_config.NumberColumn("Hours", format="%.1f"),
                                "loss_output_mwh": st.column_config.NumberColumn("Lost MWh", format="%,.1f")})

with tab_quality:
    all_events = data["failures"]
    cols = st.columns(4, border=True)
    cols[0].metric("Events with no cause code", f"{(all_events['system'] == 'Unclassified').sum():,}")
    cols[1].metric("Events with stop before start", f"{int(all_events['stop_before_start'].sum()):,}")
    neg = data["maintenance"]["is_negative"].sum()
    cols[2].metric("Negative maintenance entries", f"{int(neg):,}")
    cols[3].metric("Coal reserve readings ignored", f"{int(data['coal']['reading_invalid'].sum()):,}",
                   help="Daily coal reserve days above 40 are treated as errors and left out of the monthly average.")
    st.markdown(
        "- Duration comes from `failure_duration_hours`; the lost MWh agrees with it.\n"
        "- Events that cross a month boundary are split by hours, each part priced at its own month.\n"
        "- Maintenance cost covers Jan to Aug 2023 for the whole plant (no unit), so it is not allocated to events.")
    st.subheader("Maintenance cost")
    st.dataframe(data["maintenance"], hide_index=True, alt="Maintenance cost by month and type",
                 column_config={"expenses_rp": st.column_config.NumberColumn("Expenses (Rp)", format="%,.0f")})

with tab_kpi:
    kpi_years = sorted(data["business"]["month"].dt.year.unique())
    kpi_sel = st.multiselect("Years", kpi_years, default=kpi_years[-1:], key="kpi_years")
    st.caption("Totals and rates cover the units selected in the sidebar.")
    if not kpi_sel:
        st.info("Select at least one year.", icon=":material/info:")
    else:
        kp = monthly_kpis(data["business"], sel_units, data["coal"])
        kp = kp[kp["month"].dt.year.isin(kpi_sel)]
        for i in range(0, len(KPI_SPECS), 2):
            for col, (key, title, unit_label, zero) in zip(st.columns(2), KPI_SPECS[i:i + 2]):
                with col.container(border=True):
                    st.subheader(f"{title} ({unit_label})")
                    if kp[key].notna().any():
                        st.altair_chart(kpi_chart(kp, key, unit_label, zero), alt=f"{title} by month")
                    else:
                        st.info("No data available for this KPI.", icon=":material/info:")
                    st.caption(KPI_NOTES[key])
