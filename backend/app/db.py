"""
Thin wrapper around the Neo4j async driver.

Everything else in the app imports `get_driver()` / `run_query()` from here
instead of talking to the neo4j package directly. That means if we ever swap
drivers, add retry logic, or point at a cluster instead of a single instance,
there's exactly one place to change.
"""

from neo4j import AsyncGraphDatabase, AsyncDriver

from app.config import settings

_driver: AsyncDriver | None = None


async def get_driver() -> AsyncDriver:
    global _driver
    if _driver is None:
        _driver = AsyncGraphDatabase.driver(
            settings.neo4j_uri,
            auth=(settings.neo4j_user, settings.neo4j_password),
        )
    return _driver


async def close_driver() -> None:
    global _driver
    if _driver is not None:
        await _driver.close()
        _driver = None


async def run_query(query: str, parameters: dict | None = None) -> list[dict]:
    """Run a Cypher query and return the results as plain dicts.

    Converting neo4j.Record objects to dicts immediately (instead of passing
    them around) keeps the rest of the codebase free of Neo4j-specific types,
    which makes it much easier to unit test without a live database.
    """
    driver = await get_driver()
    async with driver.session() as session:
        result = await session.run(query, parameters or {})
        records = [record.data() async for record in result]
        return records
