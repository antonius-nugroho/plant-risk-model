"""Run the pipeline from the command line: clean, classify, price, rank risk, write CSVs."""
import argparse

from src.risk_model.data_loader import ROOT
from src.risk_model.opportunity import missing_prices, opportunity_loss
from src.risk_model.pipeline import load_all
from src.risk_model.risk import likelihood_window, revenue_by_year, risk_limits, risk_table


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
    limit_df = risk_limits(revenue_by_year(d["business"], d["pricing"]), cfg["risk_limit"]["k"])
    scale = [(i["name"], i["upper"]) for i in cfg["impact_scale"]]
    risk = risk_table(seg[seg.event_class == "risk"], d["business"], by=("unit", "system", "component"),
                      limits=dict(zip(limit_df["year"], limit_df["risk_limit_rp"])), scale=scale,
                      likelihood_scale=[(i["name"], i["upper"]) for i in cfg["likelihood_scale"]],
                      window_months=12 * len(likelihood_window(seg["month"].dt.year.unique(), cfg["max_window_years"])))

    out.mkdir(parents=True, exist_ok=True)
    for name, df in [("business", d["business"]), ("pricing", d["pricing"]), ("maintenance", d["maintenance"]),
                     ("failures", failures), ("opportunity_loss", seg), ("risk_table", risk)]:
        df.to_csv(out / f"{name}.csv", index=False, encoding="utf-8-sig")

    print("Events by class:\n", failures.groupby("event_class").size().to_string(), "\n")
    print("Events with stop < start:", int(failures.stop_before_start.sum()))
    print("Price source:", seg.price_source.iloc[0])
    for unit, months in missing_prices(seg).items():
        print(f"WARNING {unit}: no price for {', '.join(months)} (extend data/raw/Pricing.csv)")
    print("\nOpportunity loss (Rp million) by unit and class:")
    print((seg.pivot_table(index="unit", columns="event_class", values="opportunity_loss_rp", aggfunc="sum") / 1e6).round(0).to_string())
    print("\nTop 8 risks (expected annual loss, Rp million):")
    cols = ["unit", "system", "component", "events", "risk_score", "risk_band"]
    print(risk.head(8).assign(loss_m=(risk.expected_annual_loss_rp / 1e6).round(0))[cols + ["loss_m"]].to_string(index=False))


if __name__ == "__main__":
    main()
