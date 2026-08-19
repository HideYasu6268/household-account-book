"""日々の運用で叩く一括実行コマンド。

  python -m src.run_pipeline

data/raw/ に置いた新しいCSVを取り込み、未分類の取引だけ
判定(自動 or 対話)して data/processed/kakeibo_db.csv に統合する。
続けて 年月(yyyymm) x 細目 の横持ち集計(data/processed/monthly_by_subcategory.csv)
を作り直し、両CSVをGoogle Driveにアップロードする(config/settings.yaml の
drive設定が無い場合はアップロードはスキップされる)。

年月 x 科目 x 細目 の縦持ち集計は含まない(月末等、任意のタイミングで
  python -m src.summarize
を別途実行する)。
"""
from . import build_db
from . import drive_upload
from . import summarize


def main() -> None:
    build_db.import_and_classify()
    summarize.build_subcategory_pivot()
    drive_upload.upload_processed_db()


if __name__ == "__main__":
    main()
