"""
Simulates a configuration management database (CMDB) export.

In a real company this would be a nightly dump from a tool like ServiceNow
or a Terraform state file: it tells you what infrastructure is *supposed*
to exist and what *should* depend on what. It does NOT tell you what is
actually running right now -- that's the discovery and telemetry feeds'
job. Mixing those two kinds of truth together is exactly the mistake this
project is designed to avoid.

This data is generated once, with a fixed random seed, so the topology is
the same every time you run the app.
"""

import random

SEED = 42


def _build_topology():
    rng = random.Random(SEED)

    regions = [
        {"id": "us-east", "name": "US East"},
        {"id": "eu-west", "name": "EU West"},
    ]

    data_centers = []
    hosts = []
    for region in regions:
        for dc_index in range(1, 3):  # 2 data centers per region
            dc_id = f"{region['id']}-dc{dc_index}"
            data_centers.append(
                {"id": dc_id, "name": f"{region['name']} DC{dc_index}", "region_id": region["id"]}
            )
            for host_index in range(1, 6):  # 5 hosts per data center
                host_id = f"{dc_id}-host{host_index:02d}"
                hosts.append(
                    {
                        "id": host_id,
                        "hostname": f"{host_id}.internal",
                        "data_center_id": dc_id,
                        "ip_address": f"10.{rng.randint(0, 9)}.{rng.randint(0, 255)}.{host_index}",
                    }
                )

    # A small, realistic-looking service dependency chain for an e-commerce
    # style system. Each tuple is (service_id, display_name).
    service_defs = [
        ("web-frontend", "Web Frontend"),
        ("api-gateway", "API Gateway"),
        ("auth-service", "Auth Service"),
        ("catalog-service", "Catalog Service"),
        ("cart-service", "Cart Service"),
        ("checkout-service", "Checkout Service"),
        ("payment-service", "Payment Service"),
        ("ledger-service", "Ledger Service"),
        ("notification-service", "Notification Service"),
        ("search-service", "Search Service"),
        ("inventory-service", "Inventory Service"),
        ("user-profile-service", "User Profile Service"),
    ]
    services = [{"id": sid, "name": name} for sid, name in service_defs]

    # Declared dependencies: (service that needs it, service it needs).
    declared_depends_on = [
        ("web-frontend", "api-gateway"),
        ("api-gateway", "auth-service"),
        ("api-gateway", "catalog-service"),
        ("api-gateway", "cart-service"),
        ("api-gateway", "search-service"),
        ("cart-service", "inventory-service"),
        ("checkout-service", "cart-service"),
        ("checkout-service", "payment-service"),
        ("checkout-service", "user-profile-service"),
        ("payment-service", "ledger-service"),
        ("catalog-service", "inventory-service"),
        ("checkout-service", "notification-service"),
    ]

    # Declared placement: which host(s) each service is supposed to run on.
    # Spread services across hosts round-robin so no single host looks special.
    declared_runs_on = []
    for index, service in enumerate(services):
        primary_host = hosts[index % len(hosts)]
        declared_runs_on.append((service["id"], primary_host["id"]))
        # A few services are declared to run redundantly on a second host.
        if index % 3 == 0:
            secondary_host = hosts[(index + 7) % len(hosts)]
            declared_runs_on.append((service["id"], secondary_host["id"]))

    return {
        "regions": regions,
        "data_centers": data_centers,
        "hosts": hosts,
        "services": services,
        "declared_depends_on": declared_depends_on,
        "declared_runs_on": declared_runs_on,
    }


def get_cmdb_snapshot() -> dict:
    """Return the (deterministic) CMDB export. Cheap to call repeatedly."""
    return _build_topology()
