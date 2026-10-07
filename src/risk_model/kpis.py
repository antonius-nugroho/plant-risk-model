"""Monthly plant KPIs from the Business Data files."""
import numpy as np
import pandas as pd

# (column, title, axis label, start y-axis at zero)
KPI_SPECS = [
    ("net_production_gwh", "Net production", "GWh", True),
    ("cofiring_biomass_mwh", "Co-firing biomass", "MWh", True),
    ("eaf_pct", "Equivalent availability factor (EAF)", "%", False),
    ("efor_pct", "Equivalent forced outage rate (EFOR)", "%", True),
    ("sfc_kg_per_kwh", "Specific fuel consumption (SFC)", "kg/kWh", False),
    ("ncf_pct", "Net capacity factor (NCF)", "%", True),
    ("sof_pct", "Schedule outage factor (SOF)", "%", True),
    ("coal_reserve_days", "Coal reserve operations days", "days", True),
]

KPI_NOTES = {
    "net_production_gwh": "Net energy sold (kwh_netto_penjualan_kwh) / 1,000,000.",
    "cofiring_biomass_mwh": "Electricity from biomass: biomass kg x kcal/kg / gross plant heat rate (kcal/kWh) / 1,000.",
    "eaf_pct": "Reported EAF, weighted by period hours across the selected units.",
    "efor_pct": "Reported EFOR, weighted by period hours; a blank in a month the unit ran counts as 0.",
    "sfc_kg_per_kwh": "Coal burned (kg) / net energy sold (kWh).",
    "ncf_pct": "Reported NCF, weighted by period hours; a month with no production counts as 0.",
    "sof_pct": "Reported SOF, weighted by period hours; a blank (no scheduled outage) counts as 0.",
    "coal_reserve_days": "Monthly average of the daily reported coal reserve operations days. Plant level: not filtered by unit.",
}


def _wmean(values, weights):
    ok = values.notna()
    return np.average(values[ok], weights=weights[ok]) if ok.any() and weights[ok].sum() > 0 else np.nan


def monthly_kpis(business, units, coal=None):
    """One row per (year, month) for the selected units: sums for energy, period-hour-weighted means for rates."""
    b = business[business["unit"].isin(units)].copy()
    ran = b["sh_servicehours_jam"].fillna(0) > 0
    b["net_kwh"] = b["kwh_netto_penjualan_kwh"].fillna(0)
    b["biomass_kwh"] = (b["pemakaian_biomassa_kg"] * b["nilai_kalor_biomassa_kcal/kg"]
                        / b["gross_plant_heat_rate_kcal/kwh"]).fillna(0)
    b["coal_kg"] = b["pemakaian_bahan_bakar_batubara_kg"].fillna(0)
    b["sof"] = b["sof_scheduleoutagefactor_pct"].fillna(0)
    b["ncf"] = b["ncf_netcapacityfactor_pct"].fillna(0)
    b["efor"] = b["efor_equivalentforcedoutagerate_pct"].where(~(b["efor_equivalentforcedoutagerate_pct"].isna() & ran), 0.0)
    b["eaf"] = b["eaf_equivalentavailibilityfactor_pct"]
    w = b["ph_periodehours_jam"]

    rows = []
    for month, g in b.groupby("month"):
        gw = w.loc[g.index]
        rows.append({
            "month": month,
            "net_production_gwh": g["net_kwh"].sum() / 1e6,
            "cofiring_biomass_mwh": g["biomass_kwh"].sum() / 1e3,
            "eaf_pct": _wmean(g["eaf"], gw),
            "efor_pct": _wmean(g["efor"], gw),
            "sfc_kg_per_kwh": g["coal_kg"].sum() / g["net_kwh"].sum() if g["net_kwh"].sum() > 0 else np.nan,
            "ncf_pct": _wmean(g["ncf"], gw),
            "sof_pct": _wmean(g["sof"], gw),
            "coal_reserve_days": np.nan,
        })
    k = pd.DataFrame(rows)
    if coal is not None:
        days = coal.groupby(coal["date"].dt.to_period("M").dt.to_timestamp())["coal_reserve_days"].mean()
        k["coal_reserve_days"] = k["month"].map(days)
    k["year"] = k["month"].dt.year.astype(str)
    k["month_name"] = k["month"].dt.strftime("%b")
    return k
