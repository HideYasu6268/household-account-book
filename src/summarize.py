"""kakeibo_db.csv から 年月 x 科目 x 細目 の集計CSVを作る。

exclude_categories(settings.yaml)に指定した科目(カードの引落等)は
実質的な支出でないため集計から除外する。
"""
import csv
from collections import defaultdict
from pathlib import Path

from .config import load_settings

DB_PATH = Path("data/processed/kakeibo_db.csv")
OUT_PATH = Path("data/processed/monthly_summary.csv")


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


if __name__ == "__main__":
    run()
