import streamlit as st

from src.risk_model.data_loader import data_signature
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
    classes = st.pills("Event classes", list(CLASS_LABEL.values()), selection_mode="multi", default=["Risk"],
                       help="Risk: FO, FD, FD.MP, SF and trips. Loss event: MO, PD, MD, FD.SYS. "
                            "Excluded: NC, RS, PO, PE, SHD, SUD.")
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

priced = get_priced(sig, PRICE_BASIS.get(price_mode, "bpp_rp_kwh"), manual)
inv = {v: k for k, v in CLASS_LABEL.items()}
priced = priced[priced["unit"].isin(sel_units) & priced["month"].dt.year.isin(sel_years)
                & priced["event_class"].isin([inv[c] for c in classes])]
gaps = missing_prices(priced) if price_mode != "Manual" else []
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

tab_rank, tab_matrix, tab_trend, tab_events, tab_quality = st.tabs(
    ["Ranking", "Risk matrix", "Monthly loss", "Events", "Data checks"])

with tab_rank:
    top = table.head(15).assign(label=lambda t: t[by].astype(str).agg(" / ".join, axis=1),
                                loss_m=lambda t: t["expected_annual_loss_rp"] / 1e6)
    with st.container(border=True):
        st.subheader("Expected annual loss (Rp million)")
        st.bar_chart(top, x="label", y="loss_m", horizontal=True, sort="-loss_m",
                     alt="Top 15 groups by expected annual opportunity loss")
    with st.container(border=True):
        st.subheader("Risk table")
        st.dataframe(
            table.drop(columns=["period_hours", "service_hours"]), hide_index=True,
            alt="Risk table by group",
            column_config={
                "events": st.column_config.NumberColumn("Events"),
                "downtime_hours": st.column_config.NumberColumn("Downtime (h)", format="%.0f"),
                "mean_repair_hours": st.column_config.NumberColumn("Mean repair (h)", format="%.1f"),
                "lost_mwh": st.column_config.NumberColumn("Lost MWh", format="%,.0f"),
                "opportunity_loss_rp": st.column_config.NumberColumn("Opportunity loss (Rp)", format="%,.0f"),
                "events_per_year": st.column_config.NumberColumn("Events/yr", format="%.1f"),
                "mtbf_hours": st.column_config.NumberColumn("MTBF (h)", format="%.0f"),
                "mean_loss_per_event_rp": st.column_config.NumberColumn("Mean loss/event (Rp)", format="%,.0f"),
                "expected_annual_loss_rp": st.column_config.NumberColumn("Expected annual loss (Rp)", format="%,.0f"),
                "likelihood": st.column_config.NumberColumn("L (1-5)"),
                "consequence": st.column_config.NumberColumn("C (1-5)"),
                "risk_score": st.column_config.NumberColumn("Score"),
                "risk_band": st.column_config.TextColumn("Band"),
            })
    st.caption("Likelihood and consequence levels are ranks among the groups shown (1 = lowest fifth, "
               "5 = highest fifth), so they change with the filters.")

with tab_matrix:
    with st.container(border=True):
        st.subheader("Groups by likelihood and consequence")
        st.dataframe(risk_matrix(table).rename_axis(index="Likelihood", columns="Consequence")
                     .style.background_gradient(cmap="Reds", vmin=0), alt="Likelihood by consequence matrix")
    st.caption("Count of groups per cell. Likelihood: events per year. Consequence: mean loss per event.")

with tab_trend:
    monthly = priced.pivot_table(index="month", columns="unit", values="opportunity_loss_rp", aggfunc="sum") / 1e6
    with st.container(border=True):
        st.subheader("Opportunity loss by month (Rp million)")
        st.bar_chart(monthly, alt="Opportunity loss per month by unit")

with tab_events:
    show = events[["timestamp_start", "unit", "unit_status", "event_class", "failure_impact", "system",
                   "component", "root_cause_failure_analysis", "failure_duration_hours", "loss_output_mwh"]]
    st.dataframe(show, hide_index=True, alt="Failure events",
                 column_config={"failure_duration_hours": st.column_config.NumberColumn("Hours", format="%.1f"),
                                "loss_output_mwh": st.column_config.NumberColumn("Lost MWh", format="%,.1f")})

with tab_quality:
    all_events = data["failures"]
    cols = st.columns(3, border=True)
    cols[0].metric("Events with no cause code", f"{(all_events['system'] == 'Unclassified').sum():,}")
    cols[1].metric("Events with stop before start", f"{int(all_events['stop_before_start'].sum()):,}")
    neg = data["maintenance"]["is_negative"].sum()
    cols[2].metric("Negative maintenance entries", f"{int(neg):,}")
    st.markdown(
        "- Duration comes from `failure_duration_hours`; the lost MWh agrees with it.\n"
        "- Events that cross a month boundary are split by hours, each part priced at its own month.\n"
        "- Maintenance cost covers Jan to Aug 2023 for the whole plant (no unit), so it is not allocated to events.")
    st.subheader("Maintenance cost")
    st.dataframe(data["maintenance"], hide_index=True, alt="Maintenance cost by month and type",
                 column_config={"expenses_rp": st.column_config.NumberColumn("Expenses (Rp)", format="%,.0f")})
