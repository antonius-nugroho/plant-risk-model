"""Steps 2-4 + opportunity loss: load, clean, classify, price the lost energy."""
import argparse

from src.risk_model.classify import classify_events
from src.risk_model.data_loader import (ROOT, load_business, load_cause_codes, load_config,
                                        load_failures, load_maintenance, load_pricing)
from src.risk_model.opportunity import opportunity_loss


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--price", type=float, help="manual price in Rp/kWh, overrides the monthly price")
    ap.add_argument("--basis", choices=["bpp_rp_kwh", "selling_price_rp_kwh"], help="monthly price column")
    args = ap.parse_args()

    cfg = load_config()
    raw, out = ROOT / cfg["paths"]["raw"], ROOT / cfg["paths"]["processed"]
    f = cfg["files"]
    business = load_business(raw, f["business"])
    pricing = load_pricing(raw, f["pricing"])
    maint = load_maintenance(raw, f["maintenance"])
    failures = load_failures(raw, f["failure"], load_cause_codes(raw, f["cause_codes"]))
    failures = classify_events(failures, cfg["event_scope"])

    ol = cfg["opportunity_loss"]
    manual = args.price if args.price is not None else ol["manual_price_rp_per_kwh"]
    seg = opportunity_loss(failures, pricing, args.basis or ol["price_basis"], manual)

    out.mkdir(parents=True, exist_ok=True)
    for name, df in [("business", business), ("pricing", pricing), ("maintenance", maint),
                     ("failures", failures), ("opportunity_loss", seg)]:
        df.to_csv(out / f"{name}.csv", index=False, encoding="utf-8-sig")

    print("Events by class:\n", failures.groupby("event_class").size().to_string(), "\n")
    print("Unassigned statuses:", failures.loc[failures.event_class == "unassigned", "unit_status"].value_counts().to_dict())
    print("Unmapped cause codes:", failures.loc[failures.system.str.startswith("Unmapped"), "failure_cause_code"].unique().tolist())
    print("Events with stop < start:", int(failures.stop_before_start.sum()))
    print("Missing price rows:", int(seg.price_rp_kwh.isna().sum()), "| price source:", seg.price_source.iloc[0])
    print("\nOpportunity loss (Rp million) by unit and class:")
    print((seg.pivot_table(index="unit", columns="event_class", values="opportunity_loss_rp", aggfunc="sum") / 1e6).round(0).to_string())


if __name__ == "__main__":
    main()
