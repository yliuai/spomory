"""Deployment entry point for the remote MCP server (Epic 11.5):
`memory-core-mcp-remote` runs the combined FastAPI (register/quota) + MCP
(`/mcp`) service over uvicorn, wired from environment variables the same
way `memory_core.mcp_server.server.default_server()` is for the local
stdio server.
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI

from memory_core.audit import AuditLog
from memory_core.mcp_server.remote import (
    _UserStores,
    build_oauth_remote_server,
    build_remote_server,
)
from memory_core.usage import UsageTracker

from .app import create_app
from .auth import AuthStore
from .email import ResendEmailSender
from .oauth_store import OAuthStore, SpomoryOAuthProvider


def _data_dir() -> Path:
    """Where this deployment's SQLite files (auth/usage/audit) live --
    same `MEMORY_CORE_DATA_DIR` convention as the local stdio server, so a
    self-hosted deployment can point it at a persistent volume."""
    path = Path(os.environ.get("MEMORY_CORE_DATA_DIR", Path.home() / ".memory-core"))
    path.mkdir(parents=True, exist_ok=True)
    return path


def default_remote_app() -> FastAPI:
    """Build the deployable app using env-configured providers/backend."""
    from memory_core.llm.local_sentence_transformer import SentenceTransformerProvider
    from memory_core.llm.openai_compatible import OpenAICompatibleProvider

    database_url = os.environ["DATABASE_URL"]  # required: no local-SQLite fallback for the remote server
    llm = OpenAICompatibleProvider()
    embedder = SentenceTransformerProvider()
    data_dir = _data_dir()
    auth_store = AuthStore(data_dir / "memory_core_auth.sqlite3")
    usage_tracker = UsageTracker(data_dir / "memory_core_usage.sqlite3")
    audit_log = AuditLog(data_dir / "memory_core_audit.sqlite3")

    stores = _UserStores(database_url, llm)
    remote_server = build_remote_server(
        auth_store, database_url, llm, embedder, usage_tracker=usage_tracker, audit_log=audit_log, stores=stores
    )
    # Required for real traffic to be accepted at all -- see create_app's
    # docstring: no allowed_hosts means every request gets 421'd. Comma-
    # separated, e.g. "memory.example.com,memory.example.com:443".
    allowed_hosts_env = os.environ.get("MCP_ALLOWED_HOSTS", "")
    allowed_hosts = [h.strip() for h in allowed_hosts_env.split(",") if h.strip()] or None

    # Default to Claude's own web-app origin: an empty allowlist rejects
    # *any* request carrying an Origin header, which is safe against
    # arbitrary malicious sites but risks rejecting Claude's own legitimate
    # traffic if it ever sends one (see create_app's docstring). Override
    # via env if Anthropic's actual origin turns out to differ.
    allowed_origins_env = os.environ.get("MCP_ALLOWED_ORIGINS", "https://claude.ai")
    allowed_origins = [o.strip() for o in allowed_origins_env.split(",") if o.strip()] or None

    # Separate from the MCP transport's own Origin check above: this is
    # plain browser CORS for /users/register (and any other non-MCP route),
    # needed so spomory's own marketing site can submit the signup form
    # with fetch() instead of requiring users to run curl by hand. Defaults
    # to the production site's origin rather than "*" so this doesn't
    # accidentally open the registration endpoint to arbitrary web pages.
    cors_allowed_origins_env = os.environ.get("CORS_ALLOWED_ORIGINS", "https://spomory.yliuai.com")
    cors_allowed_origins = [o.strip() for o in cors_allowed_origins_env.split(",") if o.strip()] or None

    # Email sending is opt-in and independent of OAuth: set RESEND_API_KEY/
    # EMAIL_FROM to enable the email-verified /users/register/request +
    # /users/register/verify pair (see create_app's docstring for why plain
    # /users/register alone isn't safe behind a public web form) even on a
    # deployment that never turns on the full OAuth Connector flow below.
    email_sender = None
    if os.environ.get("RESEND_API_KEY"):
        email_sender = ResendEmailSender(
            api_key=os.environ["RESEND_API_KEY"], from_address=os.environ["EMAIL_FROM"]
        )

    # The absolute base URL embedded in outbound emails (registration-verify
    # and, if OAuth is also on, OAuth login links) -- defaults to
    # OAUTH_ISSUER_URL since on this deployment they're the same host, but
    # kept as its own var so email-verified registration doesn't require
    # turning on OAuth just to have a base URL to hand it.
    public_base_url = os.environ.get("PUBLIC_BASE_URL") or os.environ.get("OAUTH_ISSUER_URL")

    # OAuth is opt-in: only mounted once OAUTH_ISSUER_URL is set, so an
    # existing deployment's env file keeps working unchanged until someone
    # deliberately adds the OAuth env vars (see docs/mcp_quickstart.md's
    # "OAuth 接入" section).
    oauth_mcp_server = oauth_store = None
    issuer_url = os.environ.get("OAUTH_ISSUER_URL")
    if issuer_url:
        resource_server_url = os.environ.get("OAUTH_RESOURCE_SERVER_URL", f"{issuer_url}/mcp")
        oauth_store = OAuthStore(data_dir / "memory_core_oauth.sqlite3")
        oauth_provider = SpomoryOAuthProvider(
            oauth_store, login_base_url=issuer_url, resource_url=resource_server_url
        )
        oauth_mcp_server = build_oauth_remote_server(
            database_url,
            llm,
            embedder,
            oauth_provider,
            issuer_url=issuer_url,
            resource_server_url=resource_server_url,
            usage_tracker=usage_tracker,
            audit_log=audit_log,
            stores=stores,
        )
        assert email_sender is not None, "OAuth login needs RESEND_API_KEY/EMAIL_FROM set too"

    return create_app(
        auth_store=auth_store,
        remote_mcp_server=remote_server,
        oauth_mcp_server=oauth_mcp_server,
        oauth_store=oauth_store,
        email_sender=email_sender,
        oauth_base_url=public_base_url,
        allowed_hosts=allowed_hosts,
        allowed_origins=allowed_origins,
        cors_allowed_origins=cors_allowed_origins,
    )


def main() -> None:
    import uvicorn

    port = int(os.environ.get("PORT", "8000"))
    # proxy_headers + forwarded_allow_ips: nginx terminates TLS and forwards
    # plain HTTP to this process, so without trusting its X-Forwarded-Proto
    # header uvicorn/Starlette thinks every request is http -- this showed
    # up as a real bug (Starlette's redirect_slashes handling built a
    # "http://..." redirect for an https request). Restricted to 127.0.0.1
    # since that's the only thing nginx ever connects from on this box.
    uvicorn.run(
        default_remote_app(),
        host="0.0.0.0",
        port=port,
        proxy_headers=True,
        forwarded_allow_ips="127.0.0.1",
    )


if __name__ == "__main__":
    main()
