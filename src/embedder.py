"""multilingual-e5-small を使った埋め込み計算。

e5系モデルは "query: " / "passage: " のプレフィックスを付けることが
推奨されているため、用途別に関数を分けている。
"""
from functools import lru_cache
from typing import List

import numpy as np

MODEL_NAME = "intfloat/multilingual-e5-small"
EMBEDDING_DIM = 384


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
    prefixed = [f"passage: {t}" for t in texts]
    return model.encode(prefixed, normalize_embeddings=True, convert_to_numpy=True)


def embed_query(text: str) -> np.ndarray:
    """新しい取引の摘要(検索する側)の埋め込み。"""
    model = _get_model()
    vec = model.encode([f"query: {text}"], normalize_embeddings=True, convert_to_numpy=True)
    return vec[0]
