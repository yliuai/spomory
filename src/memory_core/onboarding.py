"""Epic 9.2: one-shot bulk import of existing notes into the memory graph.

Targets the vertical MVP's onboarding flow (技术顾问/工程师 importing project
notes, client call logs, etc.) — plain Markdown and text files today; PDF is
explicitly out of scope for this pass (per TASKS.md 9.2, "PDF 可后置").
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from memory_core.graph.incremental import IncrementalIngestor, IngestResult

_SUPPORTED_SUFFIXES = {".md", ".markdown", ".txt"}


@dataclass
class ImportSummary:
    files_imported: int
    files_skipped: list[str]
    total_new_entities: int
    total_merged_entities: int
    total_new_relations: int


def import_directory(directory: str | Path, ingestor: IncrementalIngestor) -> ImportSummary:
    """Ingest every supported file directly under ``directory`` (non-recursive).

    Each file's path is used as its `source_id`, so Epic 7's provenance
    trail points back to the original note it came from.
    """
    directory = Path(directory)
    files = sorted(p for p in directory.iterdir() if p.is_file())

    summary = ImportSummary(
        files_imported=0, files_skipped=[], total_new_entities=0,
        total_merged_entities=0, total_new_relations=0,
    )

    for path in files:
        if path.suffix.lower() not in _SUPPORTED_SUFFIXES:
            summary.files_skipped.append(path.name)
            continue

        text = path.read_text(encoding="utf-8", errors="ignore").strip()
        if not text:
            summary.files_skipped.append(path.name)
            continue

        result: IngestResult = ingestor.ingest(text, source_id=str(path))
        summary.files_imported += 1
        summary.total_new_entities += result.new_entities
        summary.total_merged_entities += result.merged_entities
        summary.total_new_relations += result.new_relations

    return summary
