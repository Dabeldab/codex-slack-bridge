from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
from collections import Counter
from datetime import datetime
from pathlib import Path

from .knowledge_ingest import (
    PRODUCT_LANE_LABELS,
    chunk_text,
    infer_product_lane,
    iter_documents,
    normalize_text,
)
from .memory import redact_secrets


DIMENSIONS = 384


def main() -> None:
    args = parse_args()
    summary = ingest_source(
        source=Path(args.source),
        memory_path=Path(args.memory),
        agent=args.agent,
        collection=args.collection,
        tags=[tag.strip() for tag in args.tags.split(",") if tag.strip()],
        importance=args.importance,
        chunk_words=args.chunk_words,
        overlap_words=args.overlap_words,
        replace=args.replace,
    )
    print(json.dumps(summary, indent=2))


def ingest_source(
    *,
    source: Path,
    memory_path: Path,
    agent: str = "global",
    collection: str = "zoom_kb",
    tags: list[str] | None = None,
    importance: float = 2.0,
    chunk_words: int = 700,
    overlap_words: int = 120,
    replace: bool = True,
) -> dict:
    if not source.exists():
        source.mkdir(parents=True, exist_ok=True)
        for lane in ("nova_wave", "nova_classic", "general", "billing"):
            (source / lane).mkdir(parents=True, exist_ok=True)

    documents = list(iter_documents(source))
    records = load_records(memory_path)
    if not documents:
        return {
            "source": str(source.resolve()),
            "memory": str(memory_path.resolve()),
            "agent": agent,
            "collection": collection,
            "added": 0,
            "skipped": 0,
            "total_records": len(records),
            "lanes": {lane: 0 for lane in ("nova_wave", "nova_classic", "general", "billing")},
            "note": "No source files found; existing vector memory was left unchanged.",
        }

    if replace:
        records = [
            record
            for record in records
            if f"source_collection:{collection}" not in (record.get("Tags") or [])
        ]

    existing = {
        str(record.get("Fingerprint") or "")
        for record in records
        if record.get("Fingerprint")
    }
    added = 0
    skipped = 0
    lanes: Counter[str] = Counter()
    tags = tags or []

    for document in documents:
        text = normalize_text(document.text)
        if not text:
            skipped += 1
            continue
        product_lane = infer_product_lane(document.path, text[:1500])
        product_label = PRODUCT_LANE_LABELS.get(product_lane, "General")
        chunks = list(chunk_text(text, max_words=chunk_words, overlap_words=overlap_words))
        for index, chunk in enumerate(chunks, start=1):
            relative = document.path.resolve()
            try:
                relative_label = str(relative.relative_to(Path.cwd().resolve()))
            except ValueError:
                relative_label = str(relative)
            source_id = f"kb:{relative_label}#{index}"
            clean_text = redact_secrets(
                "Knowledge source: {title}\n"
                "Path: {path}\n"
                "Product lane: {product_label}\n"
                "Chunk: {index}/{total}\n\n"
                "{chunk}".format(
                    title=document.title,
                    path=relative,
                    product_label=product_label,
                    index=index,
                    total=len(chunks),
                    chunk=chunk,
                )
            ).strip()
            fingerprint = sha256_hex(f"{agent}\n{source_id}\n{clean_text}")
            if fingerprint in existing:
                skipped += 1
                continue
            existing.add(fingerprint)
            record_tags = tags + [
                "knowledgebase",
                f"source_collection:{collection}",
                f"product_lane:{product_lane}",
                f"product_label:{product_label}",
                f"source:{document.path.suffix.lower().lstrip('.') or 'text'}",
                f"chunk:{index}",
            ]
            records.append(
                {
                    "Id": sha256_hex(f"{fingerprint}\n{datetime.now().timestamp()}")[:32].lower(),
                    "AgentName": agent,
                    "Text": clean_text,
                    "Source": source_id,
                    "Tags": record_tags,
                    "Importance": float(importance),
                    "CreatedAt": datetime.now().astimezone().isoformat(timespec="microseconds"),
                    "Vector": hash_embedding(clean_text),
                    "Fingerprint": fingerprint,
                }
            )
            added += 1
            lanes[product_lane] += 1

    memory_path.parent.mkdir(parents=True, exist_ok=True)
    if memory_path.exists():
        backup_path = memory_path.with_suffix(memory_path.suffix + ".bak")
        shutil.copy2(memory_path, backup_path)
    memory_path.write_text(json.dumps(records, indent=2, ensure_ascii=False), encoding="utf-8")
    return {
        "source": str(source.resolve()),
        "memory": str(memory_path.resolve()),
        "agent": agent,
        "collection": collection,
        "added": added,
        "skipped": skipped,
        "total_records": len(records),
        "lanes": {lane: lanes.get(lane, 0) for lane in ("nova_wave", "nova_classic", "general", "billing")},
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Index local KB files into Agent Chat desktop vector memory.")
    parser.add_argument("--source", default="knowledge_sources/zoom_kb")
    parser.add_argument("--memory", default="data/desktop_chat/memory_vectors.json")
    parser.add_argument("--agent", default="global")
    parser.add_argument("--collection", default="zoom_kb")
    parser.add_argument("--tags", default="nova,zoom,kb")
    parser.add_argument("--importance", type=float, default=2.0)
    parser.add_argument("--chunk-words", type=int, default=700)
    parser.add_argument("--overlap-words", type=int, default=120)
    parser.add_argument("--replace", action=argparse.BooleanOptionalAction, default=True)
    return parser.parse_args()


def load_records(path: Path) -> list[dict]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    return [item for item in data if isinstance(item, dict)]


def hash_embedding(text: str) -> list[float]:
    vector = [0.0] * DIMENSIONS
    for token in tokenize(text):
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        value = int.from_bytes(digest[:8], "little", signed=False)
        index = value % DIMENSIONS
        sign = 1.0 if (value & (1 << 63)) == 0 else -1.0
        vector[index] += sign
    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0:
        return vector
    return [value / norm for value in vector]


def tokenize(text: str) -> list[str]:
    tokens: list[str] = []
    current: list[str] = []
    for char in text:
        if char.isalnum() or char in {"_", ".", "$", "/", "-"}:
            current.append(char.lower())
        elif current:
            tokens.append("".join(current))
            current.clear()
    if current:
        tokens.append("".join(current))
    return tokens


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest().upper()


if __name__ == "__main__":
    main()
