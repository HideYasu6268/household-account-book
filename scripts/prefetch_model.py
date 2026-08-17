"""devcontainer.json の postCreateCommand から呼ばれる。
初回のみモデルをダウンロードし、以降はキャッシュを使う。
"""
from sentence_transformers import SentenceTransformer

MODEL_NAME = "cl-nagoya/ruri-v3-130m"

if __name__ == "__main__":
    print(f"モデルをダウンロードしています: {MODEL_NAME}")
    SentenceTransformer(MODEL_NAME)
    print("完了しました。")
