"""settings.yaml の読み込み。"""
from functools import lru_cache
from pathlib import Path

import yaml

SETTINGS_PATH = Path("config/settings.yaml")


@lru_cache(maxsize=1)
def load_settings() -> dict:
    with SETTINGS_PATH.open(encoding="utf-8") as f:
        return yaml.safe_load(f)
