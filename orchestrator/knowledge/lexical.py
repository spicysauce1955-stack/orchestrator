"""Lexical knowledge search (spec §8, no embeddings in MVP).

Pure file search over a set of glob `sources` rooted at a repo. Term-frequency
ranked; deterministic. Backs the MCP `search` tool.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SearchResult:
    path: str  # repo-relative
    line: int  # 1-based
    snippet: str
    score: int


def _iter_files(sources: list[str], root: Path) -> list[Path]:
    seen: dict[Path, None] = {}
    for pattern in sources:
        # Path.glob("docs/**") in Python <=3.11 yields only directories, not
        # files. Appending "/*" to produce "docs/**/*" matches files at any depth.
        patterns = [pattern]
        if pattern.endswith("/**"):
            patterns.append(pattern + "/*")
        for pat in patterns:
            for p in sorted(root.glob(pat)):
                if p.is_file():
                    seen.setdefault(p, None)
    return list(seen)


def search(query: str, sources: list[str], root: Path, *, limit: int = 10) -> list[SearchResult]:
    """Return term-frequency-ranked line matches for `query` across `sources`."""
    terms = [t for t in query.lower().split() if t]
    if not terms:
        return []
    results: list[SearchResult] = []
    for path in _iter_files(sources, root):
        try:
            text = path.read_text(errors="ignore")
        except OSError:
            continue
        rel = path.relative_to(root).as_posix()
        for lineno, raw in enumerate(text.splitlines(), start=1):
            low = raw.lower()
            score = sum(low.count(t) for t in terms)
            if score:
                results.append(SearchResult(rel, lineno, raw.strip(), score))
    results.sort(key=lambda r: (-r.score, r.path, r.line))
    return results[:limit]
