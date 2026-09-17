# Local, self-hosted Spomory MCP server (stdio transport). Installs the
# published PyPI package rather than copying repo source, so the image
# always tracks a real released version instead of drifting from it.
#
# Run with `-i` (stdio needs an attached stdin/stdout) and a persistent
# volume for /data, e.g.:
#   docker run -i --rm \
#     -e LLM_API_KEY=... \
#     -v spomory-data:/data \
#     spomory
FROM python:3.11-slim

# sentence-transformers pulls in torch; installing the CPU-only wheel first
# keeps pip from resolving the default CUDA build, which drags in several
# GB of GPU libraries this container (a CPU-bound extraction/embedding
# sidecar, no GPU available in typical hosting) never uses.
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu \
    && pip install --no-cache-dir "spomory[llm,embedding,mcp]"

ENV MEMORY_CORE_DATA_DIR=/data
VOLUME ["/data"]

RUN useradd --create-home --uid 1000 spomory \
    && mkdir -p /data \
    && chown -R spomory:spomory /data
USER spomory

ENTRYPOINT ["spomory-mcp"]
