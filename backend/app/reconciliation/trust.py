"""
Per-field conflict resolution rules.

Same idea as a survivorship table in any MDM system: when two sources
disagree about the same field, something has to decide which one wins, and
"most recent write" is not always the right answer.

- Structural/ownership fields (which region a host is in, who owns it) come
  from the CMDB. That's the system people actually maintain by hand for
  this kind of fact, and a discovery or telemetry feed has no opinion on
  "who owns this" at all.
- Live-state fields (status, last_seen) should reflect whoever reported
  most recently - the whole point of those fields is "what's true right
  now", and the CMDB is the stalest source for that by design (it's a
  slow-changing system of record, not a heartbeat).

A field with no rule listed here falls back to "most recent wins", which is
a reasonable default for anything not explicitly called out.
"""

from __future__ import annotations

CMDB_OWNS_FIELDS = {"region_id", "datacenter_id", "owner", "name"}

# Used to break ties when two observations for a most-recent-wins field
# arrive with the exact same timestamp (only matters in tests / synthetic
# data where clocks are coarse).
SOURCE_TIEBREAK_ORDER = ["cmdb", "service_mesh_discovery", "telemetry"]


def field_owner_rule(field_name: str) -> str:
    """Returns 'cmdb_wins' or 'most_recent_wins' for a given property name."""
    if field_name in CMDB_OWNS_FIELDS:
        return "cmdb_wins"
    return "most_recent_wins"
