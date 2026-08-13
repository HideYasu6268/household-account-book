"""1件の取引(支払手段・取引先・金額)から科目・細目を決定する。

流れ:
  1. 同じ支払手段の rule_list から類似度上位候補を検索
  2. 類似度が閾値以上 かつ 金額しきい値を超えていなければ自動適用
  3. それ以外は questionary で対話確認(候補から選ぶ / 新規に科目・細目を選ぶ)
  4. 金額による科目・細目の読み替え(飲料⇔昼食 等)を最後に適用
"""
import os
from typing import Dict, List, Optional, Tuple

import numpy as np
import questionary

from . import embedder
from . import rules as rules_mod


def _clear_screen() -> None:
    os.system("cls" if os.name == "nt" else "clear")


def _cosine_sim(query_vec: np.ndarray, matrix: np.ndarray) -> np.ndarray:
    if matrix.shape[0] == 0:
        return np.zeros((0,))
    # embed_query / embed_passages は正規化済みなので内積 = コサイン類似度
    return matrix @ query_vec


def suggest_candidates(
    payment_method: str, vendor_text: str, top_k: int = 5, min_similarity: float = 0.0
) -> List[Dict]:
    cache = rules_mod.build_or_load_cache()
    rules_all, vectors = cache["rules"], cache["vectors"]

    idxs = [i for i, r in enumerate(rules_all) if r["支払手段"] == payment_method]
    if not idxs:
        return []

    sub_vectors = vectors[idxs]
    query_vec = embedder.embed_query(vendor_text)
    sims = _cosine_sim(query_vec, sub_vectors)

    order = np.argsort(-sims)[:top_k]
    return [
        {"rule": rules_all[idxs[i]], "similarity": float(sims[i])}
        for i in order
        if sims[i] >= min_similarity
    ]


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


_BACK = "◀ 戻る"


def _resolve_interactively(
    payment_method: str,
    vendor_text: str,
    amount: float,
    candidates: List[Dict],
    category_master: Dict[str, List[str]],
) -> Tuple[str, str]:
    """questionaryでの対話確認。各ステップに「戻る」を用意し、
    間違って選んでも1つ前のステップに戻れるようにしている。
    """
    history: List[str] = []
    state = "candidate"
    category: Optional[str] = None
    subcategory: Optional[str] = None

    while True:
        _clear_screen()
        print(f"[{payment_method}] {vendor_text}  金額: {amount:,.0f}円\n")

        if state == "candidate":
            choices = []
            for c in candidates:
                r = c["rule"]
                label = f"{r['取引先名称']} → {r['科目']}/{r['細目']}  (類似度 {c['similarity']:.2f})"
                choices.append(questionary.Choice(title=label, value=("candidate", r)))
            choices.append(questionary.Choice(title="新しい取引先として、科目・細目を選び直す", value=("new", None)))

            selected = questionary.select("この取引をどう分類しますか?", choices=choices).ask()
            if selected is None:
                raise KeyboardInterrupt

            kind, payload = selected
            if kind == "candidate":
                category, subcategory = payload["科目"], payload["細目"]
                history.append(state)
                state = "action"
            else:
                history.append(state)
                state = "category"

        elif state == "category":
            if not category_master:
                raise RuntimeError(
                    "category_master.csv が未整備です。先に科目・細目のマスタを用意してください。"
                )
            selected = questionary.select(
                "科目を選んでください:", choices=list(category_master.keys()) + [_BACK]
            ).ask()
            if selected is None:
                raise KeyboardInterrupt
            if selected == _BACK:
                state = history.pop()
                continue

            category = selected
            history.append(state)
            state = "subcategory"

        elif state == "subcategory":
            selected = questionary.select(
                f"[{category}] の細目を選んでください:", choices=category_master[category] + [_BACK]
            ).ask()
            if selected is None:
                raise KeyboardInterrupt
            if selected == _BACK:
                state = history.pop()
                continue

            subcategory = selected
            history.append(state)
            state = "action"

        elif state == "action":
            selected = questionary.select(
                "この判定をどう扱いますか?",
                choices=["ルール登録(今後も自動適用)", "1回切り(今回のみ)", _BACK],
            ).ask()
            if selected is None:
                raise KeyboardInterrupt
            if selected == _BACK:
                state = history.pop()
                continue

            if selected.startswith("ルール登録"):
                rules_mod.add_rule(payment_method, vendor_text, category, subcategory)
            return category, subcategory


def _find_exact_match(payment_method: str, vendor_text: str) -> Optional[Dict]:
    """rule_list.csv に (支払手段, 取引先名称) が完全一致する行があれば返す。
    CSVの読み込みだけで済むため、埋め込み計算(e5)は不要。
    """
    for r in rules_mod.load_rules():
        if r["支払手段"] == payment_method and r["取引先名称"] == vendor_text:
            return r
    return None


def classify_transaction(
    payment_method: str,
    vendor_text: str,
    amount: float,
    settings: dict,
    category_master: Dict[str, List[str]],
) -> Tuple[str, str]:
    sim_settings = settings["thresholds"]["similarity"]
    amount_confirm = settings.get("thresholds", {}).get("amount_confirm", {})

    # 1. まず完全一致を確認する(e5を使わない最速パス)。
    #    rule_listにデータが溜まるほど、この完全一致で済むケースが増えていく想定。
    exact = _find_exact_match(payment_method, vendor_text)
    if exact is not None:
        limit = amount_confirm.get(exact["科目"])
        forced = limit is not None and abs(amount) > limit
        if not forced:
            category, subcategory = exact["科目"], exact["細目"]
            return apply_amount_reclassify(category, subcategory, amount, settings)

        # 高額なので、完全一致であっても念のため確認だけ求める(類似度検索はしない)
        category, subcategory = _resolve_interactively(
            payment_method, vendor_text, amount, [{"rule": exact, "similarity": 1.0}], category_master
        )
        return apply_amount_reclassify(category, subcategory, amount, settings)

    # 2. 完全一致が無い場合だけ、e5で類似候補を検索する。
    top_k = sim_settings.get("top_k", 5)
    threshold_auto = sim_settings["auto_apply"]
    threshold_show = sim_settings.get("show_candidates", 0.0)

    candidates = suggest_candidates(payment_method, vendor_text, top_k=top_k, min_similarity=threshold_show)
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