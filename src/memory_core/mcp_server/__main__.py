"""CLI entry point: `memory-core-mcp` (see pyproject.toml [project.scripts])."""

from __future__ import annotations


def main() -> None:
    from .server import default_server

    default_server().run()


if __name__ == "__main__":
    main()
