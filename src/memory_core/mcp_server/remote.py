"""Remote, HTTP-reachable MCP server (Epic 11.5): the same five tools as
`server.py`, authenticated per request instead of a single fixed local
user, and backed by one `PostgresGraphStore` per authenticated `user_id`
sharing one Postgres database.

This is the counterpart the business plan's cold-start playbook always
needed alongside the local stdio server: something installable in one step
("register, get a key, connect") for people who don't want to run a local
Python environment at all, and the deployment target for getting listed on
MCP marketplaces that require a reachable HTTPS endpoint rather than a
locally-spawned subprocess.

Two authentication mounts share the same tool logic and the same per-user
store cache (`_UserStores`) so a user's memories are one graph regardless
of which client/mount they connect through:

- `build_remote_server()` -- the original `x-api-key` header scheme (魔搭
  and any client that can't do OAuth).
- `build_oauth_remote_server()` -- full OAuth 2.1 + PKCE, required by
  Anthropic's Connector Directory. These can't share one `MCPServer`/mount:
  once an `MCPServer` is configured with `auth_server_provider` (and the
  `token_verifier` the SDK derives from it), every request to that mount
  gets wrapped in `RequireAuthMiddleware`
  (`mcp/server/lowlevel/server.py:789-801`) and rejected before it reaches
  any tool code unless it carries a valid `Authorization: Bearer` --
  breaking `x-api-key`-only clients outright. Two separate mounts (see
  `cloud_api/app.py`) avoid that instead of trying to make one endpoint
  accept both schemes.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping

from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import OAuthAuthorizationServerProvider
from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions, RevocationOptions
from mcp.server.mcpserver import Context, MCPServer

from cloud_api.auth import AuthenticatedUser, AuthStore
from memory_core.audit import AuditLog
from memory_core.graph.incremental import IncrementalIngestor
from memory_core.graph.postgres_store import PostgresGraphStore
from memory_core.llm.base import LLMProvider
from memory_core.mcp_server.server import (
    _TOOL_ANNOTATIONS,
    _add_memory,
    _export_memory,
    _forget_memory,
    _get_graph,
    _search_memory,
)
from memory_core.memory_manager.policy import RuleBasedPolicy
from memory_core.usage import UsageTracker

OAUTH_SCOPE = "memory"


def _authenticate_api_key(headers: Mapping[str, str] | None, auth_store: AuthStore) -> AuthenticatedUser:
    """Resolve the caller's identity from the request's API key.

    `ctx.headers` is client-supplied input, not an identity assertion on its
    own (see `Context.headers`'s docstring) -- this looks the key up against
    `AuthStore`'s hashed records, the same check `cloud_api.app.require_api_key`
    does for the plain-HTTP registration/quota endpoints, rather than trusting
    the header directly.
    """
    api_key = (headers or {}).get("x-api-key")
    if not api_key:
        raise PermissionError("missing x-api-key header")
    user = auth_store.authenticate(api_key)
    if user is None:
        raise PermissionError("invalid or revoked API key")
    return user


def _resolve_user_id_from_oauth() -> str:
    """The OAuth counterpart to `_authenticate_api_key`: the SDK's own
    `BearerAuthBackend` middleware already validated the `Authorization:
    Bearer` header against `SpomoryOAuthProvider.load_access_token` before
    this tool call started, and stashed the result in a contextvar (not on
    `Context` -- `Context.headers` is the only auth-adjacent thing it
    exposes). `AccessToken.subject` is the `user_id` `exchange_authorization_code`
    propagated from the authorization code (see `cloud_api/oauth_store.py`).
    """
    access_token = get_access_token()
    if access_token is None or not access_token.subject:
        raise PermissionError("missing or invalid OAuth access token")
    return access_token.subject


class _UserStores:
    """Per-`user_id` `(PostgresGraphStore, IncrementalIngestor)` cache,
    shared between the API-key and OAuth mounts so both resolve to the same
    underlying memory graph for a given user -- one Postgres connection per
    active tenant, not a shared pool (see `PostgresGraphStore`'s docstring
    for that tradeoff, deliberate for this first cut)."""

    def __init__(self, dsn: str, llm: LLMProvider) -> None:
        self._dsn = dsn
        self._llm = llm
        self._stores: dict[str, tuple[PostgresGraphStore, IncrementalIngestor]] = {}

    def resolve(self, user_id: str) -> tuple[PostgresGraphStore, IncrementalIngestor]:
        if user_id not in self._stores:
            store = PostgresGraphStore(self._dsn, user_id=user_id)
            self._stores[user_id] = (store, IncrementalIngestor(store, self._llm, policy=RuleBasedPolicy()))
        return self._stores[user_id]


def _register_tools(
    mcp: MCPServer,
    stores: _UserStores,
    embedder,
    usage_tracker: UsageTracker | None,
    audit_log: AuditLog | None,
    resolve_user_id: Callable[[Context], str],
) -> None:
    """Registers the five tools on `mcp`. `resolve_user_id` is the only
    thing that differs between the API-key mount and the OAuth mount --
    everything downstream (store resolution, usage/audit recording, the
    actual tool logic) is identical."""

    @mcp.tool(annotations=_TOOL_ANNOTATIONS["add_memory"])
    def add_memory(text: str, ctx: Context, source_id: str = "mcp-session") -> str:
        """Extract facts from `text` and write them into the memory graph."""
        user_id = resolve_user_id(ctx)
        _, ingestor = stores.resolve(user_id)
        if usage_tracker is not None:
            usage_tracker.record_event(user_id, "add_memory")
        return _add_memory(ingestor, text, source_id)

    @mcp.tool(annotations=_TOOL_ANNOTATIONS["search_memory"])
    def search_memory(query: str, ctx: Context, top_k: int = 10) -> str:
        """Retrieve and assemble a natural-language context relevant to `query`."""
        user_id = resolve_user_id(ctx)
        store, _ = stores.resolve(user_id)
        if usage_tracker is not None:
            usage_tracker.record_event(user_id, "search_memory")
        return _search_memory(store, embedder, query, top_k)

    @mcp.tool(annotations=_TOOL_ANNOTATIONS["forget_memory"])
    def forget_memory(query: str, ctx: Context) -> str:
        """Find the single fact that best matches `query` and permanently delete it."""
        user_id = resolve_user_id(ctx)
        store, _ = stores.resolve(user_id)
        if usage_tracker is not None:
            usage_tracker.record_event(user_id, "forget_memory")
        return _forget_memory(store, embedder, query, audit_log, user_id)

    @mcp.tool(annotations=_TOOL_ANNOTATIONS["get_graph"])
    def get_graph(entity_name: str, ctx: Context, hops: int = 1) -> str:
        """Return the subgraph around `entity_name` as JSON."""
        user_id = resolve_user_id(ctx)
        store, _ = stores.resolve(user_id)
        return _get_graph(store, entity_name, hops)

    @mcp.tool(annotations=_TOOL_ANNOTATIONS["export_memory"])
    def export_memory(ctx: Context, subject_id: str = "default") -> str:
        """Export the full memory graph as a JSON memory passport."""
        user_id = resolve_user_id(ctx)
        store, _ = stores.resolve(user_id)
        return _export_memory(store, subject_id)


def build_remote_server(
    auth_store: AuthStore,
    dsn: str,
    llm: LLMProvider,
    embedder,
    usage_tracker: UsageTracker | None = None,
    audit_log: AuditLog | None = None,
    stores: _UserStores | None = None,
) -> MCPServer:
    """Same five tools as `server.build_server`, multi-tenant over HTTP,
    authenticated via the `x-api-key` header. Pass `stores` explicitly to
    share its per-user cache with `build_oauth_remote_server` when mounting
    both on the same deployment."""
    mcp = MCPServer("Spomory")
    stores = stores or _UserStores(dsn, llm)

    def resolve_user_id(ctx: Context) -> str:
        return _authenticate_api_key(ctx.headers, auth_store).user_id

    _register_tools(mcp, stores, embedder, usage_tracker, audit_log, resolve_user_id)
    return mcp


def build_oauth_remote_server(
    dsn: str,
    llm: LLMProvider,
    embedder,
    oauth_provider: OAuthAuthorizationServerProvider,
    issuer_url: str,
    resource_server_url: str,
    usage_tracker: UsageTracker | None = None,
    audit_log: AuditLog | None = None,
    stores: _UserStores | None = None,
) -> MCPServer:
    """Same five tools, same per-user store cache, but this mount requires a
    real OAuth 2.1 + PKCE `Authorization: Bearer` token -- the mount
    Anthropic's Connector Directory review actually connects to.
    `client_registration_options.enabled=True` because MCP clients register
    themselves via RFC 7591 dynamic client registration; there's no flow for
    a human to pre-register a client id/secret by hand.
    """
    mcp = MCPServer(
        "Spomory",
        auth=AuthSettings(
            issuer_url=issuer_url,
            resource_server_url=resource_server_url,
            client_registration_options=ClientRegistrationOptions(
                enabled=True, valid_scopes=[OAUTH_SCOPE], default_scopes=[OAUTH_SCOPE]
            ),
            revocation_options=RevocationOptions(enabled=True),
        ),
        auth_server_provider=oauth_provider,
    )
    stores = stores or _UserStores(dsn, llm)

    def resolve_user_id(_ctx: Context) -> str:
        return _resolve_user_id_from_oauth()

    _register_tools(mcp, stores, embedder, usage_tracker, audit_log, resolve_user_id)
    return mcp
