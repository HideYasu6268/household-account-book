"""1件の取引(支払手段・取引先・金額)から科目・細目を決定する。

流れ:
  1. 同じ支払手段の rule_list から類似度上位候補を検索
  2. 類似度が閾値以上 かつ 金額しきい値を超えていなければ自動適用
  3. それ以外は questionary で対話確認(候補から選ぶ / 新規に科目・細目を選ぶ)
  4. 金額による科目・細目の読み替え(飲料⇔昼食 等)を最後に適用
"""
from typing import Dict, List, Optional, Tuple

import numpy as np
import questionary

from . import embedder
from . import rules as rules_mod


def _cosine_sim(query_vec: np.ndarray, matrix: np.ndarray) -> np.ndarray:
    if matrix.shape[0] == 0:
        return np.zeros((0,))
    # embed_query / embed_passages は正規化済みなので内積 = コサイン類似度
    return matrix @ query_vec


def suggest_candidates(payment_method: str, vendor_text: str, top_k: int = 5) -> List[Dict]:
    cache = rules_mod.build_or_load_cache()
    rules_all, vectors = cache["rules"], cache["vectors"]

    idxs = [i for i, r in enumerate(rules_all) if r["支払手段"] == payment_method]
    if not idxs:
        return []

    sub_vectors = vectors[idxs]
    query_vec = embedder.embed_query(vendor_text)
    sims = _cosine_sim(query_vec, sub_vectors)

    order = np.argsort(-sims)[:top_k]
    return [{"rule": rules_all[idxs[i]], "similarity": float(sims[i])} for i in order]


def _in_range(amount_abs: float, rule: dict) -> bool:
    if "min_exclusive" in rule and not (amount_abs > rule["min_exclusive"]):
        return False
    if "min_inclusive" in rule and not (amount_abs >= rule["min_inclusive"]):
        return False
    if "max_exclusive" in rule and not (amount_abs < rule["max_exclusive"]):
        return False
    if "max_inclusive" in rule and not (amount_abs <= rule["max_inclusive"]):
        return False
    return True


def apply_amount_reclassify(category: str, subcategory: str, amount: float, settings: dict) -> Tuple[str, str]:
    amount_abs = abs(amount)
    for rule in settings.get("thresholds", {}).get("amount_reclassify", []):
        if subcategory == rule["if_saimoku"] and _in_range(amount_abs, rule):
            return category, rule["to_saimoku"]
    return category, subcategory


def _resolve_interactively(
    payment_method: str,
    vendor_text: str,
    amount: float,
    candidates: List[Dict],
    category_master: Dict[str, List[str]],
) -> Tuple[str, str]:
    choices = []
    for c in candidates:
        r = c["rule"]
        label = f"{r['取引先名称']} → {r['科目']}/{r['細目']}  (類似度 {c['similarity']:.2f})"
        choices.append(questionary.Choice(title=label, value=("candidate", r)))
    choices.append(questionary.Choice(title="新しい取引先として、科目・細目を選び直す", value=("new", None)))

    print(f"\n[{payment_method}] {vendor_text}  金額: {amount:,.0f}円")
    selected = questionary.select("この取引をどう分類しますか?", choices=choices).ask()

    if selected is None:
        # Ctrl+C 等で中断された場合
        raise KeyboardInterrupt

    kind, payload = selected
    if kind == "candidate":
        category, subcategory = payload["科目"], payload["細目"]
    else:
        if not category_master:
            raise RuntimeError(
                "category_master.csv が未整備です。先に科目・細目のマスタを用意してください。"
            )
        category = questionary.select("科目を選んでください:", choices=sorted(category_master.keys())).ask()
        subcategory = questionary.select(
            f"[{category}] の細目を選んでください:", choices=category_master[category]
        ).ask()

    action = questionary.select(
        "この判定をどう扱いますか?",
        choices=["ルール登録(今後も自動適用)", "1回切り(今回のみ)"],
    ).ask()

    if action and action.startswith("ルール登録"):
        rules_mod.add_rule(payment_method, vendor_text, category, subcategory)

    return category, subcategory


def classify_transaction(
    payment_method: str,
    vendor_text: str,
    amount: float,
    settings: dict,
    category_master: Dict[str, List[str]],
) -> Tuple[str, str]:
    sim_settings = settings["thresholds"]["similarity"]
    top_k = sim_settings.get("top_k", 5)
    threshold_auto = sim_settings["auto_apply"]
    amount_confirm = settings.get("thresholds", {}).get("amount_confirm", {})

    candidates = suggest_candidates(payment_method, vendor_text, top_k=top_k)
    top: Optional[Dict] = candidates[0] if candidates else None

    auto_ok = top is not None and top["similarity"] >= threshold_auto
    if auto_ok:
        limit = amount_confirm.get(top["rule"]["科目"])
        if limit is not None and abs(amount) > limit:
            auto_ok = False  # 高額なので閾値に関わらず強制確認

    if auto_ok:
        category, subcategory = top["rule"]["科目"], top["rule"]["細目"]
    else:
        category, subcategory = _resolve_interactively(
            payment_method, vendor_text, amount, candidates, category_master
        )

    return apply_amount_reclassify(category, subcategory, amount, settings)
