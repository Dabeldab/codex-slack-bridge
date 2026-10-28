from __future__ import annotations

import argparse
import csv
import html
import json
import re
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from xml.etree import ElementTree

from .config import load_config
from .memory import MemoryStore, redact_secrets


SUPPORTED_EXTENSIONS = {
    ".csv",
    ".docx",
    ".htm",
    ".html",
    ".json",
    ".log",
    ".md",
    ".pdf",
    ".srt",
    ".tsv",
    ".txt",
    ".vtt",
    ".xml",
    ".yaml",
    ".yml",
}
WORD_RE = re.compile(r"\S+")
HTML_TAG_RE = re.compile(r"<[^>]+>")
VTT_TIMECODE_RE = re.compile(r"^\s*(?:\d+\s*)?(?:\d\d:)?\d\d:\d\d[.,]\d{3}\s+-->\s+")


@dataclass(frozen=True)
class SourceDocument:
    path: Path
    title: str
    text: str
    product_lane: str = "general"


PRODUCT_LANE_LABELS = {
    "nova_wave": "Nova Wave",
    "nova_classic": "Nova Classic",
    "general": "General",
    "billing": "Billing",
}


def main() -> None:
    args = parse_args()
    config = load_config(args.config)
    memory = MemoryStore(config)

    source = Path(args.source)
    if not source.exists():
        raise FileNotFoundError(f"Knowledge source does not exist: {source}")

    tags = [tag.strip() for tag in args.tags.split(",") if tag.strip()]
    documents = list(iter_documents(source))
    stored = 0
    skipped = 0
    manifest_rows: list[dict[str, object]] = []

    for document in documents:
        text = normalize_text(document.text)
        if not text:
            skipped += 1
            continue

        chunks = list(chunk_text(text, max_words=args.chunk_words, overlap_words=args.overlap_words))
        for index, chunk in enumerate(chunks, start=1):
            product_label = PRODUCT_LANE_LABELS.get(document.product_lane, "General")
            chunk_tags = tags + [
                "knowledgebase",
                f"product_lane:{document.product_lane}",
                f"product_label:{product_label}",
                f"source:{document.path.suffix.lower().lstrip('.') or 'text'}",
                f"chunk:{index}",
            ]
            memory_text = (
                f"Knowledge source: {document.title}\n"
                f"Path: {document.path.resolve()}\n"
                f"Product lane: {product_label}\n"
                f"Chunk: {index}/{len(chunks)}\n\n"
                f"{chunk}"
            )
            memory_id = memory.remember(
                agent_name=args.agent,
                text=memory_text,
                source=f"kb:{document.path.name}#{index}",
                tags=chunk_tags,
                importance=args.importance,
            )
            if memory_id:
                stored += 1
                manifest_rows.append(
                    {
                        "memory_id": memory_id,
                        "agent": args.agent,
                        "source_path": str(document.path.resolve()),
                        "product_lane": document.product_lane,
                        "chunk": index,
                        "chunks": len(chunks),
                        "tags": chunk_tags,
                        "stored_at": time.time(),
                    }
                )

    if manifest_rows:
        manifest_path = Path(args.manifest)
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        with manifest_path.open("a", encoding="utf-8", newline="\n") as handle:
            for row in manifest_rows:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    print(
        f"Ingested {stored} chunk(s) from {len(documents)} file(s) into `{args.agent}` memory. "
        f"Skipped {skipped} empty/unsupported file(s)."
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Ingest exported knowledge files into agent memory.")
    parser.add_argument("--config", default="config/agents.yaml")
    parser.add_argument("--source", default="knowledge_sources")
    parser.add_argument("--agent", default="global")
    parser.add_argument("--tags", default="nova,moira,oracle")
    parser.add_argument("--importance", type=float, default=2.0)
    parser.add_argument("--chunk-words", type=int, default=700)
    parser.add_argument("--overlap-words", type=int, default=120)
    parser.add_argument("--manifest", default="data/knowledge_ingest_manifest.jsonl")
    return parser.parse_args()


def iter_documents(source: Path) -> Iterable[SourceDocument]:
    if source.is_file():
        paths = [source]
    else:
        paths = sorted(path for path in source.rglob("*") if path.is_file())
    for path in paths:
        if path.name.startswith("."):
            continue
        if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            continue
        try:
            text = read_document_text(path)
        except Exception as exc:
            print(f"Skipped {path}: {exc}")
            continue
        yield SourceDocument(path=path, title=path.stem, text=text, product_lane=infer_product_lane(path, text[:1500]))


def infer_product_lane(path: Path, text: str = "") -> str:
    raw = f"{path.as_posix()} {text}".lower()
    compact = re.sub(r"[^a-z0-9]+", "_", raw).strip("_")
    path_parts = {part.lower() for part in path.parts}
    for lane in ("billing", "nova_classic", "nova_wave", "general"):
        if lane in path_parts:
            return lane
    if "nova_wave" in compact or "nova wave" in raw or "wave backoffice" in raw or "super nova" in raw or "nextgen" in raw or "next gen" in raw:
        return "nova_wave"
    if "nova_classic" in compact or "nova classic" in raw or "novapos" in raw or "nova pos" in raw or "sales screen" in raw:
        return "nova_classic"
    if any(term in raw for term in ("billing", "chargify", "maxio", "subscription", "past due", "payment method")):
        return "billing"
    return "general"


def read_document_text(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".txt", ".md", ".log", ".xml", ".yaml", ".yml"}:
        return path.read_text(encoding="utf-8-sig", errors="replace")
    if suffix in {".html", ".htm"}:
        raw = path.read_text(encoding="utf-8-sig", errors="replace")
        return html.unescape(HTML_TAG_RE.sub(" ", raw))
    if suffix == ".json":
        return json.dumps(json.loads(path.read_text(encoding="utf-8-sig")), indent=2, ensure_ascii=False)
    if suffix in {".csv", ".tsv"}:
        delimiter = "\t" if suffix == ".tsv" else ","
        return csv_to_text(path, delimiter=delimiter)
    if suffix == ".docx":
        return docx_to_text(path)
    if suffix == ".pdf":
        return pdf_to_text(path)
    if suffix in {".vtt", ".srt"}:
        return transcript_to_text(path)
    return ""


def csv_to_text(path: Path, *, delimiter: str) -> str:
    lines: list[str] = []
    with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as handle:
        reader = csv.reader(handle, delimiter=delimiter)
        for row in reader:
            lines.append(" | ".join(cell.strip() for cell in row if cell.strip()))
    return "\n".join(line for line in lines if line)


def docx_to_text(path: Path) -> str:
    namespace = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    paragraphs: list[str] = []
    with zipfile.ZipFile(path) as archive:
        with archive.open("word/document.xml") as document_xml:
            root = ElementTree.fromstring(document_xml.read())
    for paragraph in root.findall(".//w:p", namespace):
        pieces = [node.text or "" for node in paragraph.findall(".//w:t", namespace)]
        text = "".join(pieces).strip()
        if text:
            paragraphs.append(text)
    return "\n".join(paragraphs)


def pdf_to_text(path: Path) -> str:
    try:
        from pypdf import PdfReader  # type: ignore[import-not-found]
    except Exception as exc:
        raise RuntimeError("PDF ingestion needs optional package `pypdf`") from exc
    reader = PdfReader(str(path))
    return "\n".join((page.extract_text() or "") for page in reader.pages)


def transcript_to_text(path: Path) -> str:
    lines: list[str] = []
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.upper() == "WEBVTT" or line.isdigit():
            continue
        if VTT_TIMECODE_RE.search(line):
            continue
        lines.append(line)
    return "\n".join(lines)


def normalize_text(text: str) -> str:
    clean = redact_secrets(text)
    clean = clean.replace("\r\n", "\n").replace("\r", "\n")
    clean = re.sub(r"[ \t]+", " ", clean)
    clean = re.sub(r"\n{3,}", "\n\n", clean)
    return clean.strip()


def chunk_text(text: str, *, max_words: int, overlap_words: int) -> Iterable[str]:
    words = WORD_RE.findall(text)
    if not words:
        return
    max_words = max(max_words, 100)
    overlap_words = max(0, min(overlap_words, max_words // 2))
    start = 0
    while start < len(words):
        end = min(start + max_words, len(words))
        yield " ".join(words[start:end]).strip()
        if end == len(words):
            break
        start = end - overlap_words


if __name__ == "__main__":
    main()
