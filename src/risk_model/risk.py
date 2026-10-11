"""Likelihood, consequence and risk ranking from priced failure events."""
import numpy as np
import pandas as pd

HOURS_PER_YEAR = 8760
BANDS = [(4, "Low"), (9, "Medium"), (15, "High"), (25, "Extreme")]


def unit_exposure(business):
    """Period and service hours per unit, used to turn event counts into rates."""
    g = business.groupby("unit")[["ph_periodehours_jam", "sh_servicehours_jam"]].sum()
    return g.rename(columns={"ph_periodehours_jam": "period_hours", "sh_servicehours_jam": "service_hours"})


def revenue_by_year(business, pricing):
    """Plant revenue per year: net energy sold x selling price of the same month and unit (all units)."""
    m = business[["month", "unit", "kwh_netto_penjualan_kwh"]].merge(
        pricing[["month", "unit", "selling_price_rp_kwh"]], on=["month", "unit"], how="left")
    m["revenue_rp"] = m["kwh_netto_penjualan_kwh"].fillna(0) * m["selling_price_rp_kwh"]
    return m.groupby(m["month"].dt.year)["revenue_rp"].sum()


def risk_limits(revenue, k):
    """Risk limit per year = k x revenue of the previous year; the first year uses its own revenue."""
    rows = []
    for year in sorted(revenue.index):
        basis = year - 1 if (year - 1) in revenue.index else year
        rows.append({"year": int(year), "revenue_year": int(basis), "revenue_rp": float(revenue[basis]),
                     "risk_limit_rp": k * float(revenue[basis])})
    return pd.DataFrame(rows)


def impact_level(ratio, scale):
    """1-5 impact level of loss / risk limit. `scale` is [(name, upper_share), ...]; above the last bound = top level."""
    uppers = [u for _, u in scale[:-1]]
    ratio = pd.Series(ratio, dtype="float64")
    level = pd.Series(1 + sum((ratio > u).astype(int) for u in uppers), index=ratio.index, dtype="float64")
    return level.where(ratio.notna())


def _level(values):
    """1-5 level from the rank of each value among its peers (works for any group count)."""
    rank = values.rank(method="min")
    return np.ceil(rank / len(values) * 5).astype(int)


def _band(score):
    return next(name for limit, name in BANDS if score <= limit)


def risk_table(priced, business, by=("unit", "system"), limits=None, scale=None):
    """One row per group: how often it fails (likelihood) and what each failure costs (consequence).

    `priced` is the output of opportunity_loss(): one row per event-month.
    Expected annual loss = events per year x mean loss per event; with one year of data
    this equals the observed opportunity loss.

    Consequence level: with `limits` ({year: risk limit in Rp}) and `scale` the mean share of the
    risk limit lost per event is mapped onto the impact scale; otherwise it is a rank among the groups.
    """
    by = list(by)
    # Exposure only counts years that have failure data, so rates stay per operating year.
    business = business[business["month"].dt.year.isin(priced["month"].dt.year.unique())]
    events = priced.drop_duplicates("event_idx")
    use_scale = limits is not None and scale is not None
    if use_scale:
        event_loss = priced.groupby("event_idx")["opportunity_loss_rp"].sum().reindex(events["event_idx"]).to_numpy()
        events = events.assign(impact_ratio=event_loss / events["timestamp_start"].dt.year.map(limits).to_numpy())
    named = {"events": ("event_idx", "size"), "downtime_hours": ("failure_duration_hours", "sum"),
             "mean_repair_hours": ("failure_duration_hours", "mean")}
    if use_scale:
        named["impact_ratio"] = ("impact_ratio", "mean")
    ev = events.groupby(by).agg(**named)
    loss = priced.groupby(by).agg(lost_mwh=("lost_mwh", "sum"),
                                  opportunity_loss_rp=("opportunity_loss_rp", "sum"))
    t = ev.join(loss).reset_index()
    exp = unit_exposure(business)
    t = t.join(exp, on="unit")
    t["events_per_year"] = t["events"] / (t["period_hours"] / HOURS_PER_YEAR)
    t["mtbf_hours"] = t["service_hours"] / t["events"]
    t["mean_loss_per_event_rp"] = t["opportunity_loss_rp"] / t["events"]
    t["expected_annual_loss_rp"] = t["events_per_year"] * t["mean_loss_per_event_rp"]
    t["expected_annual_loss_mwh"] = t["events_per_year"] * t["lost_mwh"] / t["events"]
    t["likelihood"] = _level(t["events_per_year"])
    if use_scale:
        t["impact_pct"] = t["impact_ratio"] * 100
        t["consequence"] = impact_level(t["impact_ratio"], scale).fillna(_level(t["mean_loss_per_event_rp"])).astype(int)
        t["impact_scale"] = t["consequence"].map({i + 1: name for i, (name, _) in enumerate(scale)})
        t = t.drop(columns="impact_ratio")
    else:
        t["consequence"] = _level(t["mean_loss_per_event_rp"])
    t["risk_score"] = t["likelihood"] * t["consequence"]
    t["risk_band"] = t["risk_score"].map(_band)
    return t.sort_values("expected_annual_loss_rp", ascending=False, ignore_index=True)


def risk_matrix(table):
    """Count of groups in each likelihood x consequence cell (5x5, consequence across)."""
    m = pd.crosstab(table["likelihood"], table["consequence"])
    return m.reindex(index=range(5, 0, -1), columns=range(1, 6), fill_value=0)
