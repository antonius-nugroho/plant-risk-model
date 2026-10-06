"""Load and clean the raw plant files (Indonesian number format, '-' as missing)."""
from pathlib import Path

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[2]


def load_config(path=ROOT / "config.yaml"):
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def to_number(series):
    """'1.234.567,89' -> 1234567.89; '-' and blanks -> NaN."""
    s = series.astype("string").str.strip().replace({"-": pd.NA, "": pd.NA})
    s = s.str.replace(".", "", regex=False).str.replace(",", ".", regex=False)
    return pd.to_numeric(s, errors="coerce")


def _read_csv(path, **kw):
    return pd.read_csv(path, sep=";", dtype=str, encoding="utf-8-sig", **kw)


def _month(series):
    return pd.to_datetime(series.str.strip(), format="%b-%y")


def load_business(raw, name):
    df = _read_csv(raw / name)
    df.columns = [c.strip() for c in df.columns]
    out = pd.DataFrame({"month": _month(df["end_of_month"]), "unit": df["unit"].str.strip()})
    for c in df.columns.drop(["end_of_month", "unit"]):
        out[c] = to_number(df[c])
    return out


def load_pricing(raw, name):
    df = _read_csv(raw / name)
    df = df.loc[:, ~df.columns.str.startswith("Unnamed")]
    out = pd.DataFrame({"month": _month(df["month"]), "unit": df["unit_name"].str.strip()})
    for c in ["coal_price_rp_per_ton", "biomass_price_rp_per_ton", "bpp_rp_kwh", "selling_price_rp_kwh"]:
        out[c] = to_number(df[c])
    return out


def load_maintenance(raw, name):
    """Plant-level (no unit column). Negative expenses are kept and flagged."""
    df = _read_csv(raw / name)
    df = df.loc[:, ~df.columns.str.startswith("Unnamed")]
    out = pd.DataFrame({
        "month": _month(df["Month"]),
        "maintenance_type": df["Maintenance Types"].str.strip(),
        "expenses_rp": to_number(df["Expenses"]),
    })
    out["is_negative"] = out["expenses_rp"] < 0
    return out


def load_cause_codes(raw, name):
    """One row per cause-code string; the string matches failure_cause_code exactly."""
    df = _read_csv(raw / name)
    key = "Cause Code ID & Name - Component - System"
    df[key] = df[key].str.strip()
    # The same code appears once per unit type with the same system/component.
    df = df.drop_duplicates([key, "System Name", "Component Name"])
    return df.rename(columns={key: "failure_cause_code",
                              "System Name": "system",
                              "Component Name": "component"})[["failure_cause_code", "system", "component"]]


def load_failures(raw, name, cause_codes):
    df = pd.read_excel(raw / name)
    df["unit"] = df["unit_no"].str.strip()
    df["unit_status"] = df["unit_status"].str.strip()
    df["failure_cause_code"] = df["failure_cause_code"].str.strip()
    df = df.merge(cause_codes, on="failure_cause_code", how="left")
    blank = df["failure_cause_code"].isna()
    df.loc[blank, ["system", "component"]] = "Unclassified"
    unmatched = ~blank & df["system"].isna()
    df.loc[unmatched, ["system", "component"]] = "Unmapped (code not in reference)"
    # failure_duration_hours is consistent with loss_output_mwh; timestamp_stop is not always.
    df["event_end"] = df["timestamp_start"] + pd.to_timedelta(df["failure_duration_hours"], unit="h")
    df["stop_before_start"] = df["timestamp_stop"] < df["timestamp_start"]
    return df
