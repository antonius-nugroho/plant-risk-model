"""Classify failure events as risk, loss event, excluded or unassigned."""
import numpy as np


def classify_events(events, scope):
    """Add `event_class`. A status listed under excluded or loss_event decides the class;
    otherwise risk statuses and risk impacts (trips) count as risk."""
    status = events["unit_status"]
    cls = np.select(
        [status.isin(scope["excluded"]),
         status.isin(scope["loss_event"]),
         events["failure_impact"].isin(scope["risk_impacts"]) | status.isin(scope["risk"])],
        ["excluded", "loss_event", "risk"],
        default="unassigned",
    )
    return events.assign(event_class=cls)
