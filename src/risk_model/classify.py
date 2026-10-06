"""Classify failure events as risk, loss event, excluded or unassigned."""
import numpy as np


def classify_events(events, scope):
    """Add `event_class`. Risk impacts (trips) count as risk unless the status is excluded."""
    status = events["unit_status"]
    cls = np.select(
        [status.isin(scope["excluded"]),
         events["failure_impact"].isin(scope["risk_impacts"]) | status.isin(scope["risk"]),
         status.isin(scope["loss_event"])],
        ["excluded", "risk", "loss_event"],
        default="unassigned",
    )
    return events.assign(event_class=cls)
