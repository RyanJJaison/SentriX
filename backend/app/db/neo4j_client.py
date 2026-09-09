"""
Thin wrapper around the Neo4j driver (Technical Architecture §3.3).

If NEO4J_URI isn't configured — e.g. the graph store isn't up yet on a
teammate's machine — this quietly runs in mock mode so the API stays
demoable. Once real credentials are set in .env, run_query() executes
against the actual graph store with no caller-side changes needed.
"""
from neo4j import GraphDatabase

from app.core.config import settings


class Neo4jClient:
    def __init__(self):
        self._driver = None
        if settings.neo4j_uri:
            self._driver = GraphDatabase.driver(
                settings.neo4j_uri, auth=(settings.neo4j_user, settings.neo4j_password)
            )

    @property
    def mock_mode(self) -> bool:
        return self._driver is None

    def run_query(self, query: str, **params) -> list[dict]:
        if self._driver is None:
            raise RuntimeError("Neo4j is not configured — running in mock mode")
        with self._driver.session() as session:
            result = session.run(query, **params)
            return [record.data() for record in result]

    def close(self) -> None:
        if self._driver is not None:
            self._driver.close()


neo4j_client = Neo4jClient()
