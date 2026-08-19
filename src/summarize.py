"""kakeibo_db.csv から 年月 x 科目 x 細目 の集計CSVを作る。

exclude_categories(settings.yaml)に指定した科目(カードの引落等)は
実質的な支出でないため集計から除外する。
"""
import csv
from collections import defaultdict
from pathlib import Path
from typing import Dict

from .config import load_settings

DB_PATH = Path("data/processed/kakeibo_db.csv")
OUT_PATH = Path("data/processed/monthly_summary.csv")
SUBCATEGORY_OUT_PATH = Path("data/processed/monthly_by_subcategory.csv")


def run() -> None:
    settings = load_settings()
    exclude = set(settings.get("summary", {}).get("exclude_categories", []))

    totals = defaultdict(lambda: {"合計金額": 0.0, "件数": 0})

    with DB_PATH.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            if row["科目"] in exclude:
                continue
            year_month = row["日付"][:7]
            key = (year_month, row["科目"], row["細目"])
            totals[key]["合計金額"] += float(row["金額"])
            totals[key]["件数"] += 1

    rows = [
        {"年月": ym, "科目": cat, "細目": sub, "合計金額": v["合計金額"], "件数": v["件数"]}
        for (ym, cat, sub), v in sorted(totals.items())
    ]

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUT_PATH.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["年月", "科目", "細目", "合計金額", "件数"])
        writer.writeheader()
        writer.writerows(rows)

    print(f"{OUT_PATH} を出力しました({len(rows)} 行)")


def build_subcategory_pivot() -> Path:
    """年月(yyyymm)を行、細目を列とした横持ちの集計CSVを作る。

    ID列に年月(例: 202601)、以降の列に細目ごとの合計金額(支出はマイナス)。
    exclude_categories(settings.yaml)に指定した科目は集計から除外する。
    その月に取引が無い細目は 0 として埋める。
    """
    settings = load_settings()
    exclude = set(settings.get("summary", {}).get("exclude_categories", []))

    # year_month(yyyymm) -> 細目 -> 合計金額
    totals: Dict[str, Dict[str, float]] = defaultdict(lambda: defaultdict(float))
    subcategories: set = set()

    with DB_PATH.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            if row["科目"] in exclude:
                continue
            year_month = row["日付"][:7].replace("-", "")  # "2026-01" -> "202601"
            subcategory = row["細目"]
            totals[year_month][subcategory] += float(row["金額"])
            subcategories.add(subcategory)

    sorted_subcategories = sorted(subcategories)
    fieldnames = ["ID"] + sorted_subcategories

    rows = []
    for year_month in sorted(totals):
        row = {"ID": year_month}
        for subcategory in sorted_subcategories:
            row[subcategory] = totals[year_month].get(subcategory, 0.0)
        rows.append(row)

    SUBCATEGORY_OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with SUBCATEGORY_OUT_PATH.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"{SUBCATEGORY_OUT_PATH} を出力しました({len(rows)} 行 x {len(sorted_subcategories)} 細目)")
    return SUBCATEGORY_OUT_PATH


if __name__ == "__main__":
    run()
    build_subcategory_pivot()
