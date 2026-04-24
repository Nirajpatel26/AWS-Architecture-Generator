"""One-off: chunk knowledge_base/ into a FAISS + BM25 index.

Chunking strategy:
- Markdown files are split on header boundaries (# / ## / ###) so each chunk is a
  semantically coherent section. Oversized sections are further word-windowed with
  200-word overlap. HTML files are stripped then split the same way (headers are
  rarer so most end up as word-windowed chunks).
- Each chunk is tagged with metadata (service, compliance, doc_type) so the
  retriever can filter at query time.

Usage:
    python -m rag.ingest
"""
from __future__ import annotations

import json
import os
import pickle
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent
KB_DIR = ROOT / "knowledge_base"
INDEX_DIR = KB_DIR / ".index"

# Target chunk size in words. Sections smaller than this are kept whole;
# larger sections are split into overlapping windows.
TARGET_WORDS = 500
WINDOW_OVERLAP = 200

_HTML_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")

_BOILERPLATE_FILENAMES = {
    "readme.md", "contributing.md", "code_of_conduct.md", "changelog.md",
    "security.md", "support.md", "license", "license.md", "license-summary",
    "license-samplecode", "notice", "notice.md", "authors", "authors.md",
    "codeowners", "pull_request_template.md", "issue_template.md",
    "bug_report.md", "feature_request.md",
}

_SKIP_PATH_PARTS = {
    ".git", ".github", "node_modules", "images", "img", "assets",
    "sample-apps", "sample_apps", "samples", "examples", "test",
    "tests", "__tests__", "fixtures", "dist", "build", "_build",
    "iam-policies",
}

_BOILERPLATE_PHRASES = (
    "contributions are welcome",
    "we welcome contributions",
    "thank you for your interest in contributing",
    "see contributing.md",
    "licensed under the apache license",
    "copyright amazon.com",
    "this project is licensed under",
)

_MIN_CHARS = 200

# Map path tokens to canonical service names used for metadata filtering.
_SERVICE_ALIASES = {
    "apigateway": "api_gateway",
    "api_gateway": "api_gateway",
    "lambda": "lambda",
    "dynamodb": "dynamodb",
    "s3": "s3",
    "cloudfront": "cloudfront",
    "rds": "rds",
    "kms": "kms",
    "iam": "iam",
    "cognito": "cognito",
    "cloudtrail": "cloudtrail",
    "cloudwatch": "cloudwatch",
    "route53": "route53",
    "vpc": "vpc",
    "glue": "glue",
    "athena": "athena",
    "sagemaker": "sagemaker",
    "ecr": "ecr",
    "elasticache": "elasticache",
    "step_functions": "step_functions",
    "acm": "acm",
}

_COMPLIANCE_KEYWORDS = {
    "HIPAA": ("hipaa", "phi", "protected health"),
    "PCI": ("pci", "cardholder", "pci-dss", "pci dss"),
    "SOC2": ("soc2", "soc 2", "soc-2"),
}


def _strip_html(raw: str) -> str:
    raw = re.sub(r"<script[\s\S]*?</script>", " ", raw, flags=re.IGNORECASE)
    raw = re.sub(r"<style[\s\S]*?</style>", " ", raw, flags=re.IGNORECASE)
    text = _HTML_TAG.sub(" ", raw)
    return _WS.sub(" ", text).strip()


def _is_boilerplate(path: Path, text: str) -> bool:
    name = path.name.lower()
    if name in _BOILERPLATE_FILENAMES or name.startswith("license"):
        return True
    head = text[:600].lower()
    if any(phrase in head for phrase in _BOILERPLATE_PHRASES):
        return True
    if len(text.strip()) < _MIN_CHARS:
        return True
    return False


def _detect_service(path: Path) -> Optional[str]:
    for part in path.parts:
        p = part.lower()
        if p in _SERVICE_ALIASES:
            return _SERVICE_ALIASES[p]
    # Try the whole stem first (so "api_gateway.md" → api_gateway), then
    # fall back to individual tokens (so "s3_cloudfront.md" → s3).
    stem = path.stem.lower()
    if stem in _SERVICE_ALIASES:
        return _SERVICE_ALIASES[stem]
    for tok in re.split(r"[_\-.]", stem):
        if tok in _SERVICE_ALIASES:
            return _SERVICE_ALIASES[tok]
    return None


def _detect_compliance(text: str) -> List[str]:
    lower = text.lower()
    hits = []
    for tag, kws in _COMPLIANCE_KEYWORDS.items():
        if any(kw in lower for kw in kws):
            hits.append(tag)
    return hits


def _detect_doc_type(path: Path) -> str:
    parts = {p.lower() for p in path.parts}
    stem = path.stem.lower()
    if "well_architected" in stem or "well_architected" in parts:
        return "well_architected"
    if "hipaa" in stem:
        return "compliance"
    if path.suffix.lower() in {".html", ".htm"}:
        return "html_doc"
    return "service_doc"


_HEADER_RE = re.compile(r"^(#{1,3})\s+(.+?)\s*$", re.MULTILINE)


def _split_markdown_by_headers(text: str) -> List[Tuple[List[str], str]]:
    """Split markdown on #/##/### headers. Returns list of (header_path, body).

    header_path is the stack of active headers at each section, e.g.
    ["# S3", "## Encryption"]. body is the text between that header and the next.
    """
    matches = list(_HEADER_RE.finditer(text))
    if not matches:
        return [([], text.strip())]

    sections: List[Tuple[List[str], str]] = []
    # Pre-header prelude
    if matches[0].start() > 0:
        prelude = text[: matches[0].start()].strip()
        if prelude:
            sections.append(([], prelude))

    stack: List[Tuple[int, str]] = []  # (level, header_text)
    for i, m in enumerate(matches):
        level = len(m.group(1))
        header = m.group(2).strip()
        # Pop deeper-or-equal headers
        while stack and stack[-1][0] >= level:
            stack.pop()
        stack.append((level, header))
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[start:end].strip()
        header_path = [f"{'#' * lv} {h}" for lv, h in stack]
        if body:
            sections.append((header_path, body))
    return sections


def _window_words(text: str, target: int = TARGET_WORDS, overlap: int = WINDOW_OVERLAP) -> List[str]:
    """Split long text into overlapping word windows."""
    words = text.split()
    if len(words) <= target:
        return [" ".join(words)] if words else []
    step = max(1, target - overlap)
    out = []
    for i in range(0, len(words), step):
        window = words[i : i + target]
        if not window:
            break
        out.append(" ".join(window))
        if i + target >= len(words):
            break
    return out


def _chunks_from_text(text: str, is_markdown: bool) -> List[Tuple[List[str], str]]:
    """Produce (header_path, chunk_text) tuples."""
    if is_markdown:
        sections = _split_markdown_by_headers(text)
    else:
        sections = [([], text)]
    out: List[Tuple[List[str], str]] = []
    for header_path, body in sections:
        pieces = _window_words(body)
        for piece in pieces:
            if piece.strip():
                out.append((header_path, piece))
    return out


def collect_chunks() -> List[dict]:
    chunks: List[dict] = []
    if not KB_DIR.exists():
        return chunks
    skipped = 0
    for p in sorted(KB_DIR.rglob("*")):
        if not p.is_file():
            continue
        suffix = p.suffix.lower()
        if suffix not in {".md", ".txt", ".html", ".htm"}:
            continue
        parts_lower = {s.lower() for s in p.parts}
        if parts_lower & _SKIP_PATH_PARTS:
            skipped += 1
            continue
        try:
            raw = p.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        is_md = suffix in {".md", ".txt"}
        text = raw if is_md else _strip_html(raw)
        if not text.strip() or _is_boilerplate(p, text):
            skipped += 1
            continue

        service = _detect_service(p)
        doc_type = _detect_doc_type(p)
        source = str(p.relative_to(KB_DIR))

        for i, (header_path, chunk_text) in enumerate(_chunks_from_text(text, is_md)):
            compliance = _detect_compliance(chunk_text)
            chunks.append({
                "source": source,
                "chunk_id": i,
                "text": chunk_text,
                "header_path": header_path,
                "service": service,
                "compliance": compliance,
                "doc_type": doc_type,
            })
    collect_chunks.last_skipped = skipped  # type: ignore[attr-defined]
    return chunks


_TOKEN_RE = re.compile(r"[a-z0-9_]+")


def _tokenize_for_bm25(text: str) -> List[str]:
    return _TOKEN_RE.findall(text.lower())


def build_index() -> dict:
    chunks = collect_chunks()
    if not chunks:
        return {"status": "no_chunks"}
    try:
        import faiss  # type: ignore
        from sentence_transformers import SentenceTransformer  # type: ignore
    except Exception as e:
        return {"status": "missing_deps", "error": str(e)}

    model = SentenceTransformer("all-MiniLM-L6-v2")
    embeddings = model.encode(
        [c["text"] for c in chunks],
        show_progress_bar=False,
        convert_to_numpy=True,
    )
    dim = embeddings.shape[1]
    index = faiss.IndexFlatIP(dim)
    faiss.normalize_L2(embeddings)
    index.add(embeddings)

    INDEX_DIR.mkdir(parents=True, exist_ok=True)
    faiss.write_index(index, str(INDEX_DIR / "faiss.bin"))
    with open(INDEX_DIR / "chunks.pkl", "wb") as f:
        pickle.dump(chunks, f)

    # BM25 — serialize the pre-tokenized corpus so the retriever can rebuild
    # the index at load time without re-tokenizing. rank_bm25 itself pickles
    # fine, but keeping tokens lets us swap BM25 variants without reingesting.
    tokenized = [_tokenize_for_bm25(c["text"]) for c in chunks]
    with open(INDEX_DIR / "bm25_tokens.pkl", "wb") as f:
        pickle.dump(tokenized, f)

    # Aggregate metadata stats for the report
    services = sorted({c["service"] for c in chunks if c["service"]})
    doc_types = sorted({c["doc_type"] for c in chunks})
    skipped = getattr(collect_chunks, "last_skipped", 0)
    meta = {
        "count": len(chunks),
        "dim": dim,
        "skipped_files": skipped,
        "chunking": "markdown_header_aware",
        "target_words": TARGET_WORDS,
        "overlap_words": WINDOW_OVERLAP,
        "services": services,
        "doc_types": doc_types,
        "has_bm25": True,
    }
    with open(INDEX_DIR / "meta.json", "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)
    return {"status": "ok", **meta}


if __name__ == "__main__":
    print(json.dumps(build_index(), indent=2))
