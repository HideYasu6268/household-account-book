"""raw/*.csv を読み込み、未取込の取引だけ classify で判定して
data/processed/kakeibo_db.csv に追記・統合する。

既存行と (支払手段, 日付, 取引先, 金額) が一致する行は取り込み済みとみなし
スキップする(明細を重複期間でダウンロードしても二重登録されない)。
"""
import csv
import glob
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Set, Tuple

from . import classify as classify_mod
from . import rules as rules_mod
from .config import load_settings

DB_PATH = Path("data/processed/kakeibo_db.csv")
DB_FIELDS = ["支払手段", "日付", "取引先", "金額", "科目", "細目"]


def _parse_amount(raw) -> float:
    if raw is None:
        return 0.0
    s = str(raw).strip().replace(",", "").replace("¥", "")
    if s == "":
        return 0.0
    return float(s)


def _normalize_date(raw, fmt: str) -> str:
    s = str(raw).strip()
    return datetime.strptime(s, fmt).strftime("%Y-%m-%d")


def _read_source_rows(source_cfg: dict) -> List[dict]:
    rows: List[dict] = []
    for path in glob.glob(source_cfg["raw_glob"]):
        with open(path, encoding=source_cfg.get("encoding", "utf-8-sig"), newline="") as f:
            rows.extend(csv.DictReader(f))
    return rows


def _to_unified_row(source_cfg: dict, raw_row: dict) -> dict:
    cols = source_cfg["columns"]
    date = _normalize_date(raw_row[cols["date"]], cols["date_format"])
    vendor = str(raw_row[cols["vendor"]]).strip()

    if "amount" in cols:
        amount = _parse_amount(raw_row[cols["amount"]])
        if cols.get("amount_sign") == "negative":
            amount = -abs(amount)
    else:
        out = _parse_amount(raw_row.get(cols["amount_out"], ""))
        inn = _parse_amount(raw_row.get(cols["amount_in"], ""))
        amount = inn - out  # 支出はマイナス、入金はプラス

    return {
        "支払手段": source_cfg["payment_method"],
        "日付": date,
        "取引先": vendor,
        "金額": amount,
    }


def _load_existing_keys() -> Set[Tuple[str, str, str, str]]:
    if not DB_PATH.exists():
        return set()
    with DB_PATH.open(encoding="utf-8-sig", newline="") as f:
        return {
            (r["支払手段"], r["日付"], r["取引先"], r["金額"])
            for r in csv.DictReader(f)
        }


def _load_existing_rows() -> List[dict]:
    if not DB_PATH.exists():
        return []
    with DB_PATH.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def import_and_classify() -> None:
    settings = load_settings()
    category_master = rules_mod.load_category_master()
    existing_keys = _load_existing_keys()

    new_rows: List[dict] = []
    for source_cfg in settings["sources"].values():
        for raw_row in _read_source_rows(source_cfg):
            unified = _to_unified_row(source_cfg, raw_row)
            key = (unified["支払手段"], unified["日付"], unified["取引先"], str(unified["金額"]))
            if key in existing_keys:
                continue

            category, subcategory = classify_mod.classify_transaction(
                unified["支払手段"], unified["取引先"], unified["金額"], settings, category_master
            )
            unified["科目"] = category
            unified["細目"] = subcategory
            new_rows.append(unified)
            existing_keys.add(key)

    if not new_rows:
        print("新規の取引はありませんでした。")
        return

    all_rows = _load_existing_rows() + new_rows
    all_rows.sort(key=lambda r: r["日付"], reverse=True)

    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with DB_PATH.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=DB_FIELDS)
        writer.writeheader()
        writer.writerows(all_rows)

    print(f"{len(new_rows)} 件を追加しました。(合計 {len(all_rows)} 件)")


if __name__ == "__main__":
    import_and_classify()
