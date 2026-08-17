"""cl-nagoya/ruri-v3-130m(日本語特化の埋め込みモデル)を使った埋め込み計算。

Ruri v3は用途別に複数のプレフィックスを使い分ける設計になっている:
  - "検索クエリ: " … 検索時のクエリ(新しい取引の摘要)
  - "検索文書: "   … 検索対象の文書(rule_list.csv側)
"""
from functools import lru_cache
from typing import List

import numpy as np

MODEL_NAME = "cl-nagoya/ruri-v3-130m"
EMBEDDING_DIM = 512


@lru_cache(maxsize=1)
def _get_model():
    # 実際に埋め込みが必要になるまでロードしない(起動を軽くするため)
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(MODEL_NAME)


def embed_passages(texts: List[str]) -> np.ndarray:
    """rule_list.csv 側(検索される側)の埋め込み。"""
    if not texts:
        return np.zeros((0, EMBEDDING_DIM))
    model = _get_model()
    prefixed = [f"検索文書: {t}" for t in texts]
    return model.encode(prefixed, normalize_embeddings=True, convert_to_numpy=True)


def embed_query(text: str) -> np.ndarray:
    """新しい取引の摘要(検索する側)の埋め込み。"""
    model = _get_model()
    vec = model.encode([f"検索クエリ: {text}"], normalize_embeddings=True, convert_to_numpy=True)
    return vec[0]
