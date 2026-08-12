"""rule_list.csv(取引先辞書)の読み書きと、埋め込みキャッシュの管理。

キャッシュ(cache/rule_list_embeddings.npz)は rule_list.csv から
機械的に再生成できる派生物なので、Gitには含めない想定。
"""
import csv
from pathlib import Path
from typing import Dict, List

import numpy as np

from . import embedder

RULE_LIST_PATH = Path("data/rules/rule_list.csv")
CACHE_PATH = Path("cache/rule_list_embeddings.npz")
FIELDNAMES = ["支払手段", "取引先名称", "科目", "細目"]


def load_rules() -> List[Dict[str, str]]:
    if not RULE_LIST_PATH.exists():
        return []
    with RULE_LIST_PATH.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def save_rules(rules: List[Dict[str, str]]) -> None:
    RULE_LIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    with RULE_LIST_PATH.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rules)


def _rule_key(rule: Dict[str, str]) -> str:
    return f"{rule['支払手段']}::{rule['取引先名称']}"


def add_rule(payment_method: str, vendor: str, category: str, subcategory: str) -> None:
    """新しい取引先を辞書に登録する。同じ支払手段+取引先名称が
    完全一致で既に存在する場合は追加しない(重複防止)。
    """
    rules = load_rules()
    key = f"{payment_method}::{vendor}"
    if any(_rule_key(r) == key for r in rules):
        return

    rules.append(
        {
            "支払手段": payment_method,
            "取引先名称": vendor,
            "科目": category,
            "細目": subcategory,
        }
    )
    save_rules(rules)

    # rule_list.csv が更新されたのでキャッシュは作り直す
    if CACHE_PATH.exists():
        CACHE_PATH.unlink()


def build_or_load_cache() -> Dict[str, object]:
    """rule_list.csv とキャッシュを突き合わせ、未計算分だけ埋め込みを
    計算して返す。戻り値: {"rules": [...], "keys": [...], "vectors": ndarray}
    """
    rules = load_rules()
    keys = [_rule_key(r) for r in rules]

    key_to_vec: Dict[str, np.ndarray] = {}
    if CACHE_PATH.exists():
        data = np.load(CACHE_PATH, allow_pickle=True)
        for k, v in zip(data["keys"], data["vectors"]):
            key_to_vec[str(k)] = v

    missing_idx = [i for i, k in enumerate(keys) if k not in key_to_vec]
    if missing_idx:
        texts = [f"{rules[i]['支払手段']} {rules[i]['取引先名称']}" for i in missing_idx]
        new_vecs = embedder.embed_passages(texts)
        for i, vec in zip(missing_idx, new_vecs):
            key_to_vec[keys[i]] = vec

    if keys:
        vectors = np.stack([key_to_vec[k] for k in keys])
    else:
        vectors = np.zeros((0, embedder.EMBEDDING_DIM))

    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    np.savez(CACHE_PATH, keys=np.array(keys, dtype=object), vectors=vectors)

    return {"rules": rules, "keys": keys, "vectors": vectors}


def load_category_master() -> Dict[str, List[str]]:
    """category_master.csv(科目,細目)を {科目: [細目, ...]} の形で読み込む。
    ファイルが無ければ空の辞書を返す(後から用意すればよい)。
    """
    path = Path("data/master/category_master.csv")
    master: Dict[str, List[str]] = {}
    if not path.exists():
        return master
    with path.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            cat, sub = row["科目"], row["細目"]
            master.setdefault(cat, []).append(sub)
    return master
