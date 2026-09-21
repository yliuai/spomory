"""MCP Server exposing the memory graph to any MCP client (Claude Desktop, Cursor, ...).

This is the open-core developer distribution surface described in the
business plan's cold-start playbook: a real, locally-runnable tool people
can install today, backed by whatever ``GraphStoreBase`` implementation is
configured (local by default, cloud once Epic 8.2 lands).
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from mcp.server.mcpserver import Context, MCPServer
from mcp_types import ToolAnnotations

from memory_core.audit import AuditLog
from memory_core.export.exporter import export_all
from memory_core.graph.incremental import IncrementalIngestor
from memory_core.graph.local_store import LocalGraphStore, migrate_plaintext_to_encrypted
from memory_core.graph.store import GraphStoreBase
from memory_core.llm.base import LLMProvider
from memory_core.llm.embedding_base import EmbeddingProvider
from memory_core.memory_manager.policy import RuleBasedPolicy
from memory_core.retrieval.ppr import personalized_pagerank, rank_entities
from memory_core.retrieval.query_match import match_query_to_triples
from memory_core.retrieval.ranker import build_context, select_relevant_relations
from memory_core.usage import UsageTracker


def build_server(
    store: GraphStoreBase,
    llm: LLMProvider,
    embedder,
    usage_tracker: UsageTracker | None = None,
    audit_log: AuditLog | None = None,
    user_id: str = "local",
) -> MCPServer:
    """Wire the six memory tools up against a given store/llm/embedder.

    Kept as a factory function (rather than module-level globals) so tests
    can inject fakes and so Epic 8.2's cloud backend swap is a one-line change
    at the call site, not a rewrite of this module. `usage_tracker` is
    optional (Epic 9.3) — when given, add_memory/search_memory calls are
    logged for retention analysis. `audit_log` is optional (Epic 10.3) —
    when given, `forget_memory` deletions are recorded there.
    """
    mcp = MCPServer("Spomory")
    ingestor = IncrementalIngestor(store, llm, policy=RuleBasedPolicy())

    @mcp.tool(annotations=_TOOL_ANNOTATIONS["add_memory"])
    def add_memory(text: str, ctx: Context, source_id: str = "mcp-session") -> str:
        """Extract facts from `text` and write them into the memory graph."""
        if usage_tracker is not None:
            usage_tracker.record_event(user_id, "add_memory")
        return _add_memory(ingestor, text, source_id, client_name=_client_name_from_context(ctx))

    @mcp.tool(annotations=_TOOL_ANNOTATIONS["search_memory"])
    def search_memory(query: str, top_k: int = 10) -> str:
        """Retrieve and assemble a natural-language context relevant to `query`."""
        if usage_tracker is not None:
            usage_tracker.record_event(user_id, "search_memory")
        return _search_memory(store, embedder, query, top_k)

    @mcp.tool(annotations=_TOOL_ANNOTATIONS["forget_memory"])
    def forget_memory(query: str) -> str:
        """Find the single fact that best matches `query` and permanently delete it.

        This is the user-facing counterpart to the "true delete" backing
        `export_memory`'s data-ownership promise (Epic 7.3): without it,
        that capability existed at the storage layer but a user had no way
        to actually invoke it from a conversation (e.g. "forget that I
        work at X"). Deletes at most one relation per call, on purpose --
        a query vague enough to match many facts should be narrowed and
        retried rather than risk deleting the wrong ones silently.
        """
        if usage_tracker is not None:
            usage_tracker.record_event(user_id, "forget_memory")
        return _forget_memory(store, embedder, query, audit_log, user_id)

    @mcp.tool(annotations=_TOOL_ANNOTATIONS["forget_all_memory"])
    def forget_all_memory(confirm: bool = False) -> str:
        """Permanently delete the entire memory graph -- every entity and relation.

        `forget_memory` is deliberately one-fact-at-a-time; this is its
        bulk counterpart for a user who wants a clean slate (e.g. before
        re-testing, or a genuine full data wipe) instead of narrowing and
        retrying a query N times.

        `destructive_hint=True` on this tool's annotations is only a hint --
        the MCP spec doesn't require a host to gate on it, so a host that
        treats it as advisory (or an agent auto-approving destructive tools)
        could otherwise wipe everything on the first call with no human in
        the loop at all. `confirm` is the actual enforcement: the first call
        (confirm left at its default, False) never deletes anything -- it
        only reports what a real call would remove -- so triggering a wipe
        needs an explicit second call with confirm=True, regardless of what
        the host's UI does or doesn't show.
        """
        if usage_tracker is not None:
            usage_tracker.record_event(user_id, "forget_all_memory")
        return _forget_all_memory(store, audit_log, user_id, confirm=confirm)

    @mcp.tool(annotations=_TOOL_ANNOTATIONS["get_graph"])
    def get_graph(entity_name: str, hops: int = 1) -> str:
        """Return the subgraph around `entity_name` as JSON."""
        return _get_graph(store, entity_name, hops)

    @mcp.tool(annotations=_TOOL_ANNOTATIONS["export_memory"])
    def export_memory(subject_id: str = "default") -> str:
        """Export the full memory graph as a JSON memory passport."""
        return _export_memory(store, subject_id)

    return mcp


# Anthropic Connector Directory requires every tool to declare these hints;
# shared between the local (stdio) and remote (HTTP) servers since both
# register the same six tools with identical semantics.
_TOOL_ANNOTATIONS = {
    "add_memory": ToolAnnotations(
        title="Add memory", read_only_hint=False, destructive_hint=False, open_world_hint=False
    ),
    # Epic 11.4: no longer strictly read-only -- it also bumps
    # last_retrieved_at on whichever relations it shows, a non-destructive
    # metadata write, not a change to the memory content itself.
    "search_memory": ToolAnnotations(
        title="Search memory", read_only_hint=False, destructive_hint=False, open_world_hint=False
    ),
    "forget_memory": ToolAnnotations(
        title="Forget memory", read_only_hint=False, destructive_hint=True, open_world_hint=False
    ),
    "forget_all_memory": ToolAnnotations(
        title="Forget all memory", read_only_hint=False, destructive_hint=True, open_world_hint=False
    ),
    "get_graph": ToolAnnotations(
        title="Get memory graph", read_only_hint=True, destructive_hint=False, open_world_hint=False
    ),
    "export_memory": ToolAnnotations(
        title="Export memory", read_only_hint=True, destructive_hint=False, open_world_hint=False
    ),
}


def _client_name_from_context(ctx: Context | None) -> str | None:
    """The calling MCP client's declared name from its `initialize` handshake
    (e.g. `claude-ai`, `cursor`) -- `None` for a stdio server invoked outside
    a request context in tests, or a client that didn't declare `clientInfo`.
    Used to tell "the same session correcting itself" apart from "two
    different clients wrote contradicting facts" -- see
    RuleBasedPolicy.decide()'s docstring."""
    if ctx is None:
        return None
    try:
        client_params = ctx.session.client_params
    except ValueError:
        # Raised by Context.session when there's no real request behind this
        # Context -- true for a bare Context() built outside an actual call
        # (as the test harness's call_tool() does), never for a real client
        # connection. Capturing client identity is best-effort; it should
        # never be the reason add_memory itself fails.
        return None
    if client_params is None or client_params.client_info is None:
        return None
    return client_params.client_info.name


def _add_memory(
    ingestor: IncrementalIngestor, text: str, source_id: str, client_name: str | None = None
) -> str:
    result = ingestor.ingest(text, source_id=source_id, client_name=client_name)
    message = (
        f"新增实体 {result.new_entities} 个，合并已有实体 {result.merged_entities} 个，"
        f"新增关系 {result.new_relations} 条"
    )
    if result.conflicting_relation_ids:
        message += (
            f"；其中 {len(result.conflicting_relation_ids)} 条与另一个客户端此前记录的事实矛盾，"
            "两条都保留了下来，没有自动判断哪个对——可以用 get_graph 查看具体内容，"
            "需要的话再用 forget_memory 手动删掉过时的那条"
        )
    return message


def _search_memory(store: GraphStoreBase, embedder, query: str, top_k: int) -> str:
    entities = store.all_entities()
    relations = store.all_relations()
    entities_by_id = {e.id: e for e in entities}

    matches = match_query_to_triples(query, relations, entities_by_id, embedder, top_k=top_k)
    seed_ids = {r.relation.subject_id for r in matches} | {r.relation.object_id for r in matches}
    scores = personalized_pagerank(entities, relations, seed_entity_ids=list(seed_ids))
    ranked_ids = [entity_id for entity_id, _ in rank_entities(scores)]

    context = build_context(relations, entities_by_id, ranked_ids, top_k=top_k)

    # Epic 11.4: record a hit on exactly the relations that made it into the
    # rendered context, so a memory nobody has actually retrieved in a long
    # time can passively lose relevance next time (see ranker.py's
    # staleness penalty) instead of only ever being reordered/deleted by the
    # RL policy's active ADD/UPDATE/DELETE/NOOP decisions.
    now = datetime.now(UTC)
    shown = select_relevant_relations(relations, entities_by_id, ranked_ids, top_k, now=now)
    if shown:
        store.add_relations([r.model_copy(update={"last_retrieved_at": now}) for r in shown])

    return context or "没有找到相关记忆。"


def _forget_memory(
    store: GraphStoreBase, embedder, query: str, audit_log: AuditLog | None, user_id: str
) -> str:
    relations = store.all_relations()
    if not relations:
        return "记忆图谱是空的，没有可以忘记的内容。"

    entities = store.all_entities()
    entities_by_id = {e.id: e for e in entities}
    matches = match_query_to_triples(query, relations, entities_by_id, embedder, top_k=1)
    target = matches[0].relation
    subject = entities_by_id.get(target.subject_id)
    obj = entities_by_id.get(target.object_id)
    subject_name = subject.name if subject else target.subject_id
    object_name = obj.name if obj else target.object_id
    forgotten = f"{subject_name}{target.predicate}{object_name}"

    store.delete_relation(target.id)
    # An endpoint entity with no relations left is dead weight -- clean
    # it up too rather than leaving an orphan node with nothing to say
    # about it, which is what "true delete" means for Epic 7.3's promise.
    entities_deleted = 0
    for entity_id in {target.subject_id, target.object_id}:
        if not store.get_neighbors(entity_id):
            store.delete_entity(entity_id)
            entities_deleted += 1

    if audit_log is not None:
        audit_log.record_deletion(
            user_id=user_id, entities_deleted=entities_deleted, relations_deleted=1
        )

    return f"已忘记：{forgotten}"


def _forget_all_memory(
    store: GraphStoreBase, audit_log: AuditLog | None, user_id: str, confirm: bool = False
) -> str:
    entities_deleted = len(store.all_entities())
    relations_deleted = len(store.all_relations())
    if entities_deleted == 0 and relations_deleted == 0:
        return "记忆图谱是空的，没有可以忘记的内容。"

    if not confirm:
        return (
            f"这将永久删除整个记忆图谱：{entities_deleted} 个实体、{relations_deleted} 条关系，"
            "且不可恢复。还没有执行任何删除。确认要继续的话，再调用一次 "
            "forget_all_memory(confirm=true)。"
        )

    store.delete_all()

    if audit_log is not None:
        audit_log.record_deletion(
            user_id=user_id, entities_deleted=entities_deleted, relations_deleted=relations_deleted
        )

    return f"已清空整个记忆图谱：删除了 {entities_deleted} 个实体、{relations_deleted} 条关系"


def _get_graph(store: GraphStoreBase, entity_name: str, hops: int) -> str:
    matches = store.find_entities_by_name(entity_name)
    if not matches:
        return "{}"
    entity_ids = [e.id for e in matches]
    entities, relations = store.query_subgraph(entity_ids, hops=hops)
    return _subgraph_to_json(entities, relations)


def _export_memory(store: GraphStoreBase, subject_id: str) -> str:
    return export_all(store, subject_id=subject_id).model_dump_json(by_alias=True)


def _subgraph_to_json(entities, relations) -> str:
    import json

    return json.dumps(
        {
            "entities": [e.model_dump(mode="json") for e in entities],
            "relations": [r.model_dump(mode="json") for r in relations],
        },
        ensure_ascii=False,
    )


def _data_dir() -> Path:
    """Where the local SQLite files live. Deliberately an *absolute* path
    under MEMORY_CORE_DATA_DIR (default ``~/.memory-core``), not a bare
    relative filename — a GUI app spawning this as a subprocess (e.g.
    Claude Desktop) may launch it with an unpredictable/unwritable working
    directory, so a relative path silently creates the db wherever that
    happened to be (or fails outright, e.g. under a sandboxed/TCC-protected
    cwd like ~/Documents on macOS)."""
    import os

    path = Path(os.environ.get("MEMORY_CORE_DATA_DIR", Path.home() / ".memory-core"))
    path.mkdir(parents=True, exist_ok=True)
    return path


def _select_store_from_env() -> GraphStoreBase:
    """Epic 8.2: DATABASE_URL set -> Postgres cloud backend; unset -> local SQLite.

    Factored out from ``default_server()`` so the branch is testable without
    also needing a real LLM_API_KEY / downloading an embedding model.
    """
    import os

    database_url = os.environ.get("DATABASE_URL")
    if database_url:
        from memory_core.graph.postgres_store import PostgresGraphStore

        # Single-tenant use of the Postgres backend (one desktop client
        # pointed at a shared DB) -- matches build_server()'s own
        # user_id="local" default. Multi-tenant isolation (Epic 11.5) lives
        # in remote.py, which builds one PostgresGraphStore per authenticated
        # user_id instead of this fixed sentinel.
        return PostgresGraphStore(database_url, user_id="local")

    db_path = _data_dir() / "memory_core.sqlite3"
    encryption_key = _load_or_create_encryption_key()
    migrate_plaintext_to_encrypted(db_path, encryption_key)
    return LocalGraphStore(db_path, encryption_key=encryption_key)


def _select_embedder_from_env() -> EmbeddingProvider:
    """EMBEDDING_PROVIDER unset/"sentence_transformers" (default) -> local
    sentence-transformers model, unchanged from before; "openai_compatible"
    -> talk to any OpenAI-compatible /v1/embeddings server instead (vLLM,
    Ollama, llama.cpp, or MLX's mlx_lm.server / vllm-mlx / mlx-openai-server
    -- they all speak this same protocol as of 2026). The second path pulls
    in no local ML framework at all (no sentence-transformers, no torch),
    which is the point for a fully-local deployment that's already running
    one of those engines for LLM extraction: no reason to also drag in a
    second, heavier framework just for embeddings.

    Factored out from ``default_server()`` for the same testability reason
    as ``_select_store_from_env()``.
    """
    import os

    provider = os.environ.get("EMBEDDING_PROVIDER", "sentence_transformers")
    if provider == "openai_compatible":
        from memory_core.llm.openai_compatible_embedding import OpenAICompatibleEmbeddingProvider

        return OpenAICompatibleEmbeddingProvider()
    if provider == "sentence_transformers":
        from memory_core.llm.local_sentence_transformer import SentenceTransformerProvider

        return SentenceTransformerProvider()
    raise ValueError(
        f"Unknown EMBEDDING_PROVIDER {provider!r}; expected "
        "'sentence_transformers' or 'openai_compatible'"
    )


def _load_or_create_encryption_key() -> bytes:
    """Epic 11.2: local storage is encrypted at rest by default, no config
    needed. The key lives next to the database rather than in a secrets
    manager or prompted from the user -- reasonable for a single-user local
    desktop tool where the threat model is "someone reads the db file/backup
    off disk," not "the same machine is fully compromised" (which would also
    expose a key read from anywhere else on that machine)."""
    from cryptography.fernet import Fernet

    key_path = _data_dir() / "encryption.key"
    if key_path.exists():
        return key_path.read_bytes()
    key = Fernet.generate_key()
    key_path.write_bytes(key)
    key_path.chmod(0o600)
    return key


def default_server() -> MCPServer:
    """Build a server using env-configured providers and backend."""
    from memory_core.llm.openai_compatible import OpenAICompatibleProvider

    store = _select_store_from_env()
    llm = OpenAICompatibleProvider()
    embedder = _select_embedder_from_env()
    usage_tracker = UsageTracker(_data_dir() / "memory_core_usage.sqlite3")
    audit_log = AuditLog(_data_dir() / "memory_core_audit.sqlite3")
    return build_server(store, llm, embedder, usage_tracker=usage_tracker, audit_log=audit_log)
