"""data/raw/ 配下のCSVを読み込み、未取込の取引だけ classify で判定して
data/processed/kakeibo_db.csv に追記・統合する。

ファイル名ではなく中身(1列目のヘッダー名 or 1行目のデータ値)で
どの形式(LIFEカード/JCBデビット/みずほ口座)かを自動判定するため、
3種類そろっていなくても、置いてあるファイルだけ処理される。

既存行と (支払手段, 日付, 取引先, 金額) が一致する行は取り込み済みとみなし
スキップする(明細を重複期間でダウンロードしても二重登録されない)。
"""
import csv
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from . import classify as classify_mod
from . import rules as rules_mod
from .config import load_settings

DB_PATH = Path("data/processed/kakeibo_db.csv")
DB_FIELDS = ["支払手段", "日付", "取引先", "金額", "科目", "細目"]


def _detect_source_key(
    header: List[str], first_data_row: Optional[List[str]], sources: Dict[str, dict]
) -> Optional[str]:
    """CSVの中身(1列目のヘッダー名 or 1行目のデータ値)からsourceを判定する。"""
    for key, cfg in sources.items():
        detect = cfg.get("detect", {})
        dtype = detect.get("type")
        value = detect.get("value")

        if dtype == "header_first_column":
            if header and header[0].strip() == value:
                return key
        elif dtype == "first_data_value":
            if first_data_row and first_data_row[0].strip() == value:
                return key
    return None


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


def _iter_raw_rows(settings: dict):
    """data/raw/ 配下の全CSVを中身で判定しながら読み込む。
    yield (source_key, source_cfg, raw_row_dict)
    形式を判定できなかったファイルは警告して読み飛ばす。
    """
    raw_dir = Path(settings.get("raw_dir", "data/raw"))
    encoding = settings.get("encoding", "utf-8-sig")
    sources = settings["sources"]

    if not raw_dir.exists():
        return

    for path in sorted(raw_dir.glob("*.csv")):
        with path.open(encoding=encoding, newline="") as f:
            rows = list(csv.reader(f))

        if not rows:
            continue

        header = rows[0]
        first_data_row = rows[1] if len(rows) > 1 else None
        source_key = _detect_source_key(header, first_data_row, sources)

        if source_key is None:
            print(f"[警告] 形式を判定できなかったためスキップしました: {path}")
            continue

        source_cfg = sources[source_key]
        for row in rows[1:]:
            if not row:
                continue
            yield source_key, source_cfg, dict(zip(header, row))


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
    for source_key, source_cfg, raw_row in _iter_raw_rows(settings):
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
