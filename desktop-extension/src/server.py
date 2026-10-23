"""Entry point for the Spomory Desktop Extension (.mcpb).

`uv run` resolves this directory's pyproject.toml (installing the real
`spomory` package from PyPI on first launch) and then runs this file,
which just hands off to the same MCP server the uvx/pip install paths
use -- no logic lives here.
"""

from __future__ import annotations

from memory_core.mcp_server.__main__ import main

if __name__ == "__main__":
    main()
