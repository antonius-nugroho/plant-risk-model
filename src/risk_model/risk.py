"""Likelihood, consequence and risk ranking from priced failure events."""
import numpy as np
import pandas as pd

HOURS_PER_YEAR = 8760
BANDS = [(4, "Low"), (9, "Medium"), (15, "High"), (25, "Extreme")]


def unit_exposure(business):
    """Period and service hours per unit, used to turn event counts into rates."""
    g = business.groupby("unit")[["ph_periodehours_jam", "sh_servicehours_jam"]].sum()
    return g.rename(columns={"ph_periodehours_jam": "period_hours", "sh_servicehours_jam": "service_hours"})


def _level(values):
    """1-5 level from the rank of each value among its peers (works for any group count)."""
    rank = values.rank(method="min")
    return np.ceil(rank / len(values) * 5).astype(int)


def _band(score):
    return next(name for limit, name in BANDS if score <= limit)


def risk_table(priced, business, by=("unit", "system")):
    """One row per group: how often it fails (likelihood) and what each failure costs (consequence).

    `priced` is the output of opportunity_loss(): one row per event-month.
    Expected annual loss = events per year x mean loss per event; with one year of data
    this equals the observed opportunity loss.
    """
    by = list(by)
    # Exposure only counts years that have failure data, so rates stay per operating year.
    business = business[business["month"].dt.year.isin(priced["month"].dt.year.unique())]
    events = priced.drop_duplicates("event_idx")
    ev = events.groupby(by).agg(events=("event_idx", "size"),
                                downtime_hours=("failure_duration_hours", "sum"),
                                mean_repair_hours=("failure_duration_hours", "mean"))
    loss = priced.groupby(by).agg(lost_mwh=("lost_mwh", "sum"),
                                  opportunity_loss_rp=("opportunity_loss_rp", "sum"))
    t = ev.join(loss).reset_index()
    exp = unit_exposure(business)
    t = t.join(exp, on="unit")
    t["events_per_year"] = t["events"] / (t["period_hours"] / HOURS_PER_YEAR)
    t["mtbf_hours"] = t["service_hours"] / t["events"]
    t["mean_loss_per_event_rp"] = t["opportunity_loss_rp"] / t["events"]
    t["expected_annual_loss_rp"] = t["events_per_year"] * t["mean_loss_per_event_rp"]
    t["likelihood"] = _level(t["events_per_year"])
    t["consequence"] = _level(t["mean_loss_per_event_rp"])
    t["risk_score"] = t["likelihood"] * t["consequence"]
    t["risk_band"] = t["risk_score"].map(_band)
    return t.sort_values("expected_annual_loss_rp", ascending=False, ignore_index=True)


def risk_matrix(table):
    """Count of groups in each likelihood x consequence cell (5x5, consequence across)."""
    m = pd.crosstab(table["likelihood"], table["consequence"])
    return m.reindex(index=range(5, 0, -1), columns=range(1, 6), fill_value=0)
