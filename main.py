"""Run the pipeline from the command line: clean, classify, price, rank risk, write CSVs."""
import argparse

from src.risk_model.data_loader import ROOT
from src.risk_model.opportunity import opportunity_loss
from src.risk_model.pipeline import load_all
from src.risk_model.risk import risk_table


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--price", type=float, help="manual price in Rp/kWh, overrides the monthly price")
    ap.add_argument("--basis", choices=["bpp_rp_kwh", "selling_price_rp_kwh"], help="monthly price column")
    args = ap.parse_args()

    d = load_all()
    cfg, failures = d["cfg"], d["failures"]
    out = ROOT / cfg["paths"]["processed"]
    ol = cfg["opportunity_loss"]
    manual = args.price if args.price is not None else ol["manual_price_rp_per_kwh"]
    seg = opportunity_loss(failures, d["pricing"], args.basis or ol["price_basis"], manual)
    risk = risk_table(seg[seg.event_class == "risk"], d["business"], by=("unit", "system", "component"))

    out.mkdir(parents=True, exist_ok=True)
    for name, df in [("business", d["business"]), ("pricing", d["pricing"]), ("maintenance", d["maintenance"]),
                     ("failures", failures), ("opportunity_loss", seg), ("risk_table", risk)]:
        df.to_csv(out / f"{name}.csv", index=False, encoding="utf-8-sig")

    print("Events by class:\n", failures.groupby("event_class").size().to_string(), "\n")
    print("Events with stop < start:", int(failures.stop_before_start.sum()))
    print("Missing price rows:", int(seg.price_rp_kwh.isna().sum()), "| price source:", seg.price_source.iloc[0])
    print("\nOpportunity loss (Rp million) by unit and class:")
    print((seg.pivot_table(index="unit", columns="event_class", values="opportunity_loss_rp", aggfunc="sum") / 1e6).round(0).to_string())
    print("\nTop 8 risks (expected annual loss, Rp million):")
    cols = ["unit", "system", "component", "events", "risk_score", "risk_band"]
    print(risk.head(8).assign(loss_m=(risk.expected_annual_loss_rp / 1e6).round(0))[cols + ["loss_m"]].to_string(index=False))


if __name__ == "__main__":
    main()
