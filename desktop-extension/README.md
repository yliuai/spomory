Source for `spomory.mcpb`, a Claude Desktop [Desktop Extension](https://www.anthropic.com/engineering/desktop-extensions) — download, double-click, click Install, no terminal or JSON editing.

`src/server.py` is a thin wrapper; `uv run` resolves `pyproject.toml` and installs the real `spomory` package from PyPI on first launch, same as the `uvx` install path everywhere else in this repo's docs. `EMBEDDING_PROVIDER=openai_compatible` is hardcoded in `manifest.json` so the extension never needs `sentence-transformers`/`torch` — a non-technical user double-clicking an installer shouldn't be stuck waiting on a 100+MB download with no progress indicator.

To rebuild after bumping the `spomory` version on PyPI:

```bash
cd desktop-extension
# bump "version" in manifest.json to match
npx @anthropic-ai/mcpb pack . spomory.mcpb
cp spomory.mcpb ../../website/public/downloads/spomory.mcpb
```

Then rebuild and redeploy the website.
