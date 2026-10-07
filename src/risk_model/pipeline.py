"""Load, clean and classify everything once; shared by main.py and the Streamlit app."""
from .classify import classify_events
from .data_loader import (ROOT, load_business, load_cause_codes, load_coal, load_config, load_failures,
                          load_maintenance, load_pricing)


def load_all():
    cfg = load_config()
    raw, f = ROOT / cfg["paths"]["raw"], cfg["files"]
    ref = ROOT / cfg["paths"]["column_description"]
    failures = load_failures(raw, f["failure"], load_cause_codes(ref, f["cause_codes"]))
    return {
        "cfg": cfg,
        "business": load_business(raw, f["business"]),
        "pricing": load_pricing(raw, f["pricing"]),
        "coal": load_coal(raw, f["coal"]),
        "maintenance": load_maintenance(raw, f["maintenance"]),
        "failures": classify_events(failures, cfg["event_scope"]),
    }
