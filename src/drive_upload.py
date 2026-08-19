"""data/processed/kakeibo_db.csv をGoogle Driveの指定フォルダにアップロードする。

初回実行時はブラウザでOAuth認証が必要(Googleアカウントでログインし、
このアプリにDriveへのアクセスを許可する)。以降は data/token.json に
保存されたトークンを再利用するため、ブラウザ操作は不要になる。

事前準備:
  1. Google Cloud Console (https://console.cloud.google.com/) で
     プロジェクトを作成し、「Google Drive API」を有効化する。
  2. 「APIとサービス」→「認証情報」→「OAuthクライアントID」を作成
     (アプリケーションの種類: デスクトップアプリ)。
  3. ダウンロードしたJSONを data/client_secret.json として保存する
     (このファイル名・配置場所は config/settings.yaml の
     drive.client_secret_path で変更可能)。
  4. pip install -r requirements.txt

data/token.json と data/client_secret.json は機密情報のため、
.gitignore で除外済み。誤ってコミットしないよう注意。
"""
from pathlib import Path
from typing import List, Optional

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

from .config import load_settings

# Drive上のファイル読み書きに限定したスコープ
# (このアプリが作成/操作したファイルのみアクセス可能。Drive全体は見えない)
SCOPES = ["https://www.googleapis.com/auth/drive.file"]


def _get_credentials(token_path: Path, client_secret_path: Path) -> Credentials:
    creds: Optional[Credentials] = None

    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not client_secret_path.exists():
                raise FileNotFoundError(
                    f"OAuthクライアントシークレットが見つかりません: {client_secret_path}\n"
                    "Google Cloud ConsoleでOAuthクライアントID(デスクトップアプリ)を作成し、\n"
                    f"ダウンロードしたJSONを {client_secret_path} に配置してください。"
                )
            flow = InstalledAppFlow.from_client_secrets_file(
                str(client_secret_path), SCOPES
            )
            # ローカルサーバーを一時起動してブラウザ認証を受け取る(初回のみ)
            creds = flow.run_local_server(port=0)

        token_path.parent.mkdir(parents=True, exist_ok=True)
        token_path.write_text(creds.to_json(), encoding="utf-8")

    return creds


def _find_existing_file_id(service, filename: str, folder_id: str) -> Optional[str]:
    """同名ファイルが既にフォルダ内にあればそのfile_idを返す(なければNone)。"""
    query = (
        f"name = '{filename}' and '{folder_id}' in parents "
        "and trashed = false"
    )
    results = service.files().list(
        q=query, spaces="drive", fields="files(id, name)"
    ).execute()
    files = results.get("files", [])
    return files[0]["id"] if files else None


def upload_csv(csv_path: Path, folder_id: str, token_path: Path, client_secret_path: Path) -> str:
    """csv_pathのファイルをfolder_idのフォルダにアップロードする。

    同名ファイルが既に存在する場合は上書き更新し、なければ新規作成する。
    戻り値: アップロードされたファイルのDrive URL
    """
    if not csv_path.exists():
        raise FileNotFoundError(f"アップロード対象が見つかりません: {csv_path}")

    creds = _get_credentials(token_path, client_secret_path)
    service = build("drive", "v3", credentials=creds)

    filename = csv_path.name
    media = MediaFileUpload(str(csv_path), mimetype="text/csv", resumable=True)

    existing_id = _find_existing_file_id(service, filename, folder_id)
    if existing_id:
        file = service.files().update(fileId=existing_id, media_body=media).execute()
        file_id = file["id"]
    else:
        metadata = {"name": filename, "parents": [folder_id]}
        file = service.files().create(
            body=metadata, media_body=media, fields="id"
        ).execute()
        file_id = file["id"]

    return f"https://drive.google.com/file/d/{file_id}/view"


def upload_processed_db() -> List[str]:
    """config/settings.yaml の drive設定を読み、data/processed/ 配下の
    アップロード対象CSV(kakeibo_db.csv、月次×細目まとめ)をアップロードする。
    drive設定が無ければ何もせず空リストを返す(既存の運用に影響を与えない)。
    """
    settings = load_settings()
    drive_cfg = settings.get("drive")
    if not drive_cfg:
        print("[情報] config/settings.yaml に drive 設定が無いため、アップロードをスキップしました。")
        return []

    folder_id = drive_cfg["folder_id"]
    token_path = Path(drive_cfg.get("token_path", "data/token.json"))
    client_secret_path = Path(drive_cfg.get("client_secret_path", "data/client_secret.json"))

    targets = [
        Path("data/processed/kakeibo_db.csv"),
        Path("data/processed/monthly_by_subcategory.csv"),
    ]

    urls = []
    for csv_path in targets:
        if not csv_path.exists():
            print(f"[情報] {csv_path} が無いためアップロードをスキップしました。")
            continue
        url = upload_csv(csv_path, folder_id, token_path, client_secret_path)
        print(f"[完了] Google Driveにアップロードしました: {csv_path.name} -> {url}")
        urls.append(url)

    return urls


if __name__ == "__main__":
    upload_processed_db()
