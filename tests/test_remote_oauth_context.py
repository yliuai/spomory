"""Unit coverage for remote.py's OAuth identity resolution
(_resolve_user_id_from_oauth) that doesn't need a real Postgres -- the
Postgres-dependent end-to-end version (a real tool call authenticated via
Authorization: Bearer through build_oauth_remote_server) lives in
test_remote_mcp_server.py, gated the same way the rest of that file is.
"""

import pytest

pytest.importorskip("mcp")

from mcp.server.auth.middleware.auth_context import auth_context_var
from mcp.server.auth.middleware.bearer_auth import AuthenticatedUser
from mcp.server.auth.provider import AccessToken

from memory_core.mcp_server.remote import _resolve_user_id_from_oauth


def test_resolve_user_id_from_oauth_reads_the_contextvar():
    access_token = AccessToken(token="t", client_id="c", scopes=["memory"], subject="user-7")
    token = auth_context_var.set(AuthenticatedUser(access_token))
    try:
        assert _resolve_user_id_from_oauth() == "user-7"
    finally:
        auth_context_var.reset(token)


def test_resolve_user_id_from_oauth_rejects_missing_context():
    with pytest.raises(PermissionError):
        _resolve_user_id_from_oauth()


def test_resolve_user_id_from_oauth_rejects_token_without_subject():
    access_token = AccessToken(token="t", client_id="c", scopes=["memory"], subject=None)
    token = auth_context_var.set(AuthenticatedUser(access_token))
    try:
        with pytest.raises(PermissionError):
            _resolve_user_id_from_oauth()
    finally:
        auth_context_var.reset(token)
