"""Small, in-memory BM25 index over current source and Markdown lines."""

import hashlib
import math
import os
import re
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

SKIP_DIRS = {".git", ".venv", "venv", "node_modules", "__pycache__", ".eval-logs",
             "tests", "hidden_tests", "_target_tests", ".codex", ".agents"}
SKIP_FILES = {"reference.json", "evaluation.json", "task.json"}


def terms(text: str) -> list[str]:
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", text)
    words = re.findall(r"[a-z0-9]+", text.lower())
    # Literal Chinese matching only; this does not translate Chinese queries to English.
    for run in re.findall(r"[\u3400-\u9fff]+", text):
        words.extend(run if len(run) == 1 else [run[i:i + 2] for i in range(len(run) - 1)])
    return words


@dataclass(frozen=True)
class Chunk:
    path: str
    start_line: int
    end_line: int
    content: str
    content_hash: str


class KeywordIndex:
    def __init__(self, workspace: Path, allowed_sources=None, chunk_lines: int = 40):
        self.workspace = workspace.resolve()
        if not self.workspace.is_dir():
            raise ValueError("Search workspace must be an existing directory")
        if not isinstance(chunk_lines, int) or isinstance(chunk_lines, bool) or chunk_lines < 1:
            raise ValueError("chunk_lines must be a positive integer")
        self.allowed_sources = set(allowed_sources) if allowed_sources is not None else None
        self.chunk_lines = chunk_lines
        self.fingerprint = None
        self.chunks = []
        self.counts = []
        self.document_frequency = Counter()
        self.average_length = 1.0

    def _files(self):
        result = {}
        size = 0
        for folder, directories, files in os.walk(self.workspace, followlinks=False):
            base = Path(folder)
            directories[:] = sorted(name for name in directories if name not in SKIP_DIRS
                                    and not (base / name).is_symlink()
                                    and (base / name).resolve().is_relative_to(self.workspace))
            for name in sorted(files):
                path = base / name
                relative = path.relative_to(self.workspace).as_posix()
                if path.suffix.lower() not in {".py", ".md"} or name in SKIP_FILES:
                    continue
                if path.suffix.lower() == ".py" and self.allowed_sources is not None and relative not in self.allowed_sources:
                    continue
                if path.is_symlink() or not path.resolve().is_relative_to(self.workspace):
                    continue
                file_size = path.stat().st_size
                if file_size > 1_000_000 or size + file_size > 4_000_000 or len(result) >= 500:
                    raise ValueError("Search corpus exceeds the 500-file / 1 MB per-file / 4 MB total limit")
                data = path.read_bytes()
                data.decode("utf-8")  # Fail explicitly on unsupported input, never silently corrupt citations.
                result[relative] = data
                size += len(data)
        return result

    def refresh(self) -> dict:
        started = time.perf_counter()
        files = self._files()
        digest = hashlib.sha256()
        for path, data in sorted(files.items()):
            digest.update(path.encode() + b"\0" + data + b"\0")
        fingerprint = digest.hexdigest()
        cache_hit = fingerprint == self.fingerprint
        scan_seconds = time.perf_counter() - started
        build_started = time.perf_counter()
        if not cache_hit:
            chunks = []
            for path, data in sorted(files.items()):
                lines = data.decode("utf-8").splitlines()
                content_hash = hashlib.sha256(data).hexdigest()
                # Fixed non-overlapping line chunks; AST/overlapping chunk experiments are later work.
                for offset in range(0, len(lines), self.chunk_lines):
                    content = "\n".join(lines[offset:offset + self.chunk_lines])
                    if content.strip():
                        chunks.append(Chunk(path, offset + 1, min(offset + self.chunk_lines, len(lines)), content, content_hash))
            self.chunks = chunks
            self.counts = [Counter(terms(chunk.path + "\n" + chunk.content)) for chunk in chunks]
            self.document_frequency = Counter(term for count in self.counts for term in count)
            self.average_length = sum(sum(count.values()) for count in self.counts) / max(1, len(self.counts)) or 1.0
            self.fingerprint = fingerprint
        return {"index_hash": fingerprint, "files": len(files), "chunks": len(self.chunks), "cache_hit": cache_hit,
                "scan_seconds": round(scan_seconds, 6),
                "build_seconds": round(time.perf_counter() - build_started, 6) if not cache_hit else 0.0}

    def rank(self, query: str) -> list[tuple[float, Chunk]]:
        query_terms = set(terms(query))
        size = len(self.chunks)
        ranked = []
        for chunk, count in zip(self.chunks, self.counts):
            length = sum(count.values())
            score = 0.0
            for term in sorted(query_terms):
                frequency = count[term]
                if frequency:
                    df = self.document_frequency[term]
                    idf = math.log(1 + (size - df + 0.5) / (df + 0.5))
                    normalizer = frequency + 1.2 * (0.25 + 0.75 * length / self.average_length)
                    score += idf * frequency * 2.2 / normalizer
            if score > 0:
                ranked.append((score, chunk))
        return sorted(ranked, key=lambda item: (-item[0], item[1].path, item[1].start_line))
