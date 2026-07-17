"""auspex-knowledge index + embedding model constants — probe-pinned.

Every value here traces to docs/probes/2026-07-17-opensearch-knn-ml.md:
- ONNX format (TORCH_SCRIPT fails to deploy on 2.19.4 — reality bite);
- dim 384, lucene/hnsw/cosinesimil (bounded [0,1] scores, efficient filter);
- `ids` is keyword because the standard analyzer splits CVE-2024-3400 into
  3 tokens — the exact-ID rail cannot live on an analyzed field.
"""

KNOWLEDGE_INDEX = "auspex-knowledge"  # auspex-* prefix (D-009 convention)

EMBED_MODEL_NAME = "huggingface/sentence-transformers/all-MiniLM-L6-v2"
EMBED_MODEL_VERSION = "1.0.2"
EMBED_MODEL_FORMAT = "ONNX"  # pinned: TORCH_SCRIPT of this model is broken on 2.19.4
EMBED_DIM = 384

KNOWLEDGE_MAPPING: dict = {
    "settings": {
        "index": {
            "knn": True,
            "number_of_shards": 1,
            "number_of_replicas": 0,  # single-node dev; prod overrides at create time
        }
    },
    "mappings": {
        # strict: a typo'd field at ingest is a bug, not a new feature
        "dynamic": "strict",
        "properties": {
            "doc_id": {"type": "keyword"},
            "chunk_index": {"type": "integer"},
            "ids": {"type": "keyword"},  # exact-match rail (term/prefix), normalized upper
            "title": {"type": "text", "fields": {"raw": {"type": "keyword"}}},
            "content": {"type": "text"},  # standard analyzer — BM25 leg
            "doc_type": {"type": "keyword"},  # cve | technique | concept
            "source": {"type": "keyword"},
            "source_ref": {"type": "keyword"},
            "severity": {"type": "keyword"},
            "cvss_score": {"type": "float"},
            "workspace_id": {"type": "keyword"},  # "" = global; scoping rails come later
            "ingested_at": {"type": "date"},
            "embedding": {
                "type": "knn_vector",
                "dimension": EMBED_DIM,
                "method": {
                    "name": "hnsw",
                    "engine": "lucene",
                    "space_type": "cosinesimil",
                    "parameters": {"m": 16, "ef_construction": 128},
                },
            },
        },
    },
}

# Search-time _source filter: vectors never ride back over the wire
# (SARA convention, sara_retriever.py:493).
SOURCE_EXCLUDES = ["embedding"]
