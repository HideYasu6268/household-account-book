"""data/raw/ 配下のCSVを読み込み、未取込の取引だけ classify で判定して
data/processed/kakeibo_db.csv に追記・統合する。

ファイル名ではなく中身(1列目のヘッダー名 or 1行目のデータ値)で
どの形式(LIFEカード/JCBデビット/みずほ口座)かを自動判定するため、
3種類そろっていなくても、置いてあるファイルだけ処理される。

既存行と (支払手段, 日付, 取引先, 金額) が一致する行は取り込み済みとみなし
スキップする(明細を重複期間でダウンロードしても二重登録されない)。
"""
import csv
import io
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from . import classify as classify_mod
from . import rules as rules_mod
from .config import load_settings

DB_PATH = Path("data/processed/kakeibo_db.csv")
DB_FIELDS = ["支払手段", "日付", "取引先", "金額", "科目", "細目"]

# 実際のカード会社・銀行の生エクスポートは Shift-JIS(cp932) のことが多いため、
# 指定のencodingで読めなければ自動でこちらにフォールバックする。
FALLBACK_ENCODINGS = ["cp932"]


class UnifiedRowError(Exception):
    """生データの列マッピングが settings.yaml と噛み合わないときのエラー。"""


def _read_csv_rows(path: Path, primary_encoding: str) -> Tuple[List[str], List[dict]]:
    """primary_encodingで読めなければ FALLBACK_ENCODINGS を順に試す。"""
    last_error: Optional[Exception] = None
    text: Optional[str] = None
    used_encoding = primary_encoding

    for enc in [primary_encoding] + FALLBACK_ENCODINGS:
        try:
            with path.open(encoding=enc, newline="") as f:
                text = f.read()
            used_encoding = enc
            break
        except UnicodeDecodeError as e:
            last_error = e
            continue

    if text is None:
        raise UnicodeDecodeError(
            last_error.encoding, last_error.object, last_error.start, last_error.end,
            f"{path} をどの文字コード({[primary_encoding] + FALLBACK_ENCODINGS})でも読み込めませんでした。"
        ) if last_error else RuntimeError(f"{path} を読み込めませんでした。")

    if used_encoding != primary_encoding:
        print(f"[情報] {path} は {primary_encoding} で読めなかったため {used_encoding} で読み込みました。")

    reader = csv.DictReader(io.StringIO(text))
    header = reader.fieldnames or []
    rows = list(reader)
    return header, rows


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
            if first_data_row and str(first_data_row[0]).strip() == value:
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
    yield (source_key, source_cfg, file_path, raw_row_dict)
    形式を判定できなかったファイルは警告して読み飛ばす。
    csv.DictReader を使うため、引用符付きフィールド(金額にカンマを含む等)でも
    列がずれない。
    """
    raw_dir = Path(settings.get("raw_dir", "data/raw"))
    encoding = settings.get("encoding", "utf-8-sig")
    sources = settings["sources"]

    if not raw_dir.exists():
        return

    for path in sorted(raw_dir.glob("*.csv")):
        header, rows = _read_csv_rows(path, encoding)

        if not header:
            continue

        first_data_row = [rows[0].get(h, "") for h in header] if rows else None
        source_key = _detect_source_key(header, first_data_row, sources)

        if source_key is None:
            print(f"[警告] 形式を判定できなかったためスキップしました: {path}")
            print(f"       検出されたヘッダー: {header}")
            continue

        source_cfg = sources[source_key]
        for row in rows:
            # ヘッダーのような行（すべての値がキー名と同じ）をフィルタリング
            is_header_row = all(str(row.get(k, "")).strip() == k.strip() for k in header)
            if is_header_row:
                print(f"[情報] ヘッダー重複行をスキップ: {path}")
                continue
            yield source_key, source_cfg, path, row


def _to_unified_row(source_key: str, source_cfg: dict, path: Path, raw_row: dict) -> dict:
    cols = source_cfg["columns"]

    def _get(col_key: str):
        col_name = cols[col_key]
        if col_name not in raw_row:
            raise UnifiedRowError(
                f"列 '{col_name}'({col_key})が見つかりません。\n"
                f"  ファイル: {path}\n"
                f"  判定されたソース: {source_key}\n"
                f"  実際のヘッダー: {list(raw_row.keys())}\n"
                f"  → config/settings.yaml の sources.{source_key}.columns.{col_key} を"
                f" 実際の列名に合わせて修正してください。"
            )
        return raw_row[col_name]

    try:
        date = _normalize_date(_get("date"), cols["date_format"])
    except ValueError as e:
        print(f"[エラー] 日付解析エラー: {e}")
        print(f"  ファイル: {path}")
        print(f"  ソース: {source_key}")
        print(f"  raw_row キー: {list(raw_row.keys())}")
        print(f"  raw_row 内容: {raw_row}")
        raise
    vendor = str(_get("vendor")).strip()

    if "amount" in cols:
        amount = _parse_amount(_get("amount"))
        if cols.get("amount_sign") == "negative":
            # 通常の利用(生データはプラス表記)は支出としてマイナス化。
            # 返品・キャンセル等で生データがマイナス表記の場合は、符号を反転させる
            # ことで支出の取り消し(プラス)として扱う。abs()で強制マイナス化すると
            # このケースを支出として二重計上してしまうため、単純反転にしている。
            amount = -amount
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


def _write_db(rows: List[dict]) -> None:
    sorted_rows = sorted(rows, key=lambda r: r["日付"], reverse=True)
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with DB_PATH.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=DB_FIELDS)
        writer.writeheader()
        writer.writerows(sorted_rows)


def import_and_classify() -> None:
    settings = load_settings()
    category_master = rules_mod.load_category_master()
    existing_keys = _load_existing_keys()
    all_rows = _load_existing_rows()

    added_count = 0
    skipped_count = 0
    try:
        for source_key, source_cfg, path, raw_row in _iter_raw_rows(settings):
            try:
                unified = _to_unified_row(source_key, source_cfg, path, raw_row)
            except (UnifiedRowError, ValueError) as e:
                print(f"[警告] 行をスキップ: {e}")
                skipped_count += 1
                continue
            
            key = (unified["支払手段"], unified["日付"], unified["取引先"], str(unified["金額"]))
            if key in existing_keys:
                continue

            category, subcategory = classify_mod.classify_transaction(
                unified["支払手段"], unified["取引先"], unified["金額"], settings, category_master, unified["日付"]
            )
            unified["科目"] = category
            unified["細目"] = subcategory

            all_rows.append(unified)
            existing_keys.add(key)
            added_count += 1

            # 1件処理するたびに保存する。途中で中断しても、ここまでの分は残る。
            _write_db(all_rows)

    except KeyboardInterrupt:
        print(f"\n中断しました。ここまでの {added_count} 件は保存済みです。残りは次回の実行時に処理されます。")
        return

    if added_count == 0:
        print("新規の取引はありませんでした。")
    else:
        print(f"{added_count} 件を追加しました。(合計 {len(all_rows)} 件)")
    if skipped_count > 0:
        print(f"({skipped_count} 件は形式エラーでスキップされました)")


if __name__ == "__main__":
    import_and_classify()