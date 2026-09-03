import pytest

from memory_core.graph.local_store import LocalGraphStore

from .graph_store_contract import GraphStoreContractTests


class TestLocalGraphStoreContract(GraphStoreContractTests):
    @pytest.fixture
    def store(self, tmp_path):
        return LocalGraphStore(tmp_path / "contract.sqlite3")
