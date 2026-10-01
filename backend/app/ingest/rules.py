"""
Pure reconciliation rules -- no database, no network, no randomness.

These are the actual decisions the system makes when sources disagree. They
are pulled out into plain functions (instead of being buried inside Cypher
queries) for two reasons:

1. They're the part of this project most worth unit testing. A bug in "is
   this fact stale?" silently makes the whole graph untrustworthy.
2. Keeping decision logic separate from I/O means we can change how we
   store the graph later (different database, caching layer, whatever)
   without touching the rules themselves.
"""

from datetime import datetime, timezone


def is_stale(last_seen_iso: str | None, now: datetime, ttl_seconds: float) -> bool:
    """A fact is stale if we haven't re-confirmed it within the TTL window.

    `last_seen_iso` being None means we have never observed it directly
    (e.g. a CMDB-declared placement discovery hasn't confirmed yet) -- that
    counts as stale too, since we have no live evidence it's still true.
    """
    if last_seen_iso is None:
        return True
    last_seen = datetime.fromisoformat(last_seen_iso)
    age_seconds = (now - last_seen).total_seconds()
    return age_seconds > ttl_seconds


def dependency_confidence(declared: bool, observed: bool) -> tuple[str, float]:
    """Decide how much to trust a DEPENDS_ON edge given what each source says.

    Why this matters: the CMDB and the discovery feed disagree with each
    other constantly in real infrastructure. Instead of picking one source
    and ignoring the other (which silently throws away information), we keep
    both opinions and label the edge with how much agreement backs it up.
    Downstream consumers (like the impact-analysis query, or a human looking
    at the graph) can then decide how much to trust a low-confidence edge.
    """
    if declared and observed:
        return "declared+observed", 1.0
    if observed and not declared:
        # Discovery found a real dependency nobody documented. This is
        # valuable, not an error -- undeclared coupling is exactly the kind
        # of thing architecture diagrams miss.
        return "observed-only (undeclared)", 0.7
    if declared and not observed:
        # The CMDB thinks this dependency should exist, but nothing has
        # confirmed it recently. Could be a stale CMDB entry, could be a
        # dependency that's only exercised on rare code paths.
        return "declared-only (unconfirmed)", 0.3
    raise ValueError("dependency_confidence called with neither source reporting it")


def runs_on_state(declared: bool, observed_now: bool, previously_stale: bool) -> str:
    """Classify a Service->Host placement as active, stale, or orphaned.

    - active: discovery is currently confirming it.
    - stale: declared (or previously active) but discovery hasn't confirmed
      it within the TTL -- might still be true, just unconfirmed.
    - orphaned: discovery is observing it but the CMDB never declared it at
      all (someone deployed something outside the normal process).
    """
    if observed_now:
        return "active" if declared else "orphaned (undeclared placement)"
    if declared:
        return "stale" if previously_stale or True else "active"
    return "orphaned (undeclared placement)"


def classify_health(status: str, stale: bool) -> str:
    """Combine a raw up/down report with staleness into one health label.

    A host that explicitly reports "down" is clearly unhealthy. A host that
    simply hasn't reported in a while is a *different* problem (it might be
    fine, we just can't see it) and the frontend should visually distinguish
    the two rather than lumping them together as "red".
    """
    if status == "down":
        return "unhealthy"
    if stale:
        return "unknown (no recent heartbeat)"
    return "healthy"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
