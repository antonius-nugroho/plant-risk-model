"""Opportunity loss = lost energy x price of the month the energy was lost."""
import pandas as pd


def split_by_month(events):
    """One row per event-month, lost MWh shared in proportion to hours inside each month."""
    rows = []
    for idx, e in events.iterrows():
        start, end = e["timestamp_start"], e["event_end"]
        total_h = (end - start).total_seconds() / 3600
        if total_h <= 0:
            rows.append((idx, start.to_period("M").to_timestamp(), 1.0))
            continue
        for m in pd.period_range(start, end, freq="M"):
            lo, hi = max(start, m.start_time), min(end, m.end_time + pd.Timedelta(microseconds=1))
            share = max((hi - lo).total_seconds() / 3600, 0) / total_h
            if share > 0:
                rows.append((idx, m.to_timestamp(), share))
    seg = pd.DataFrame(rows, columns=["event_idx", "month", "share"])
    out = events.loc[seg["event_idx"]].reset_index(names=None).drop(columns="index", errors="ignore")
    out["month"] = seg["month"].to_numpy()
    out["lost_mwh"] = out["loss_output_mwh"] * seg["share"].to_numpy()
    out["event_idx"] = seg["event_idx"].to_numpy()
    return out


def attach_price(segments, pricing, price_basis="bpp_rp_kwh", manual_price=None):
    """Monthly price per unit, or a manual Rp/kWh (single number or {unit: number})."""
    out = segments.merge(pricing[["month", "unit", price_basis]], on=["month", "unit"], how="left")
    out = out.rename(columns={price_basis: "price_rp_kwh"})
    out["price_source"] = price_basis
    if manual_price is not None:
        out["price_rp_kwh"] = out["unit"].map(manual_price) if isinstance(manual_price, dict) else manual_price
        out["price_source"] = "manual"
    out["opportunity_loss_rp"] = out["lost_mwh"] * 1000 * out["price_rp_kwh"]
    return out


def opportunity_loss(events, pricing, price_basis="bpp_rp_kwh", manual_price=None):
    return attach_price(split_by_month(events), pricing, price_basis, manual_price)
