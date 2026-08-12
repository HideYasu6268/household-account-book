"""日々の運用で叩く一括実行コマンド。

  python -m src.run_pipeline

data/raw/ に置いた新しいCSVを取り込み、未分類の取引だけ
判定(自動 or 対話)して data/processed/kakeibo_db.csv に統合する。

月次集計は含まない(月末等、任意のタイミングで
  python -m src.summarize
を別途実行する)。
"""
from . import build_db


def main() -> None:
    build_db.import_and_classify()


if __name__ == "__main__":
    main()
