"""data/processed/kakeibo_db.csv (直近数か月分のみ) と
monthly_by_subcategory.csv をGoogle Driveの指定フォルダにアップロードする。

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
import csv
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

DEFAULT_RECENT_MONTHS = 3


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


def upload_csv(
    csv_path: Path,
    folder_id: str,
    token_path: Path,
    client_secret_path: Path,
    drive_filename: Optional[str] = None,
) -> str:
    """csv_pathのファイルをfolder_idのフォルダにアップロードする。

    drive_filenameを指定すると、Drive上のファイル名をローカルのファイル名と
    変えられる(直近分だけに絞った一時ファイルを元のファイル名で上げたい場合など)。
    同名ファイルが既に存在する場合は上書き更新し、なければ新規作成する。
    戻り値: アップロードされたファイルのDrive URL
    """
    if not csv_path.exists():
        raise FileNotFoundError(f"アップロード対象が見つかりません: {csv_path}")

    creds = _get_credentials(token_path, client_secret_path)
    service = build("drive", "v3", credentials=creds)

    filename = drive_filename or csv_path.name
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


def _filter_recent_months(csv_path: Path, months: int, out_path: Path) -> Path:
    """csv_path(kakeibo_db.csv)から直近N か月分の行だけを抜き出し、
    out_path に書き出す。「直近」はデータ中の最新の日付を基準に判定する
    (実行日ではない。締め忘れがあっても意図通りの月数が取れるように)。
    """
    with csv_path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames or []
        rows = list(reader)

    if not rows:
        year_months: set = set()
    else:
        year_months = {row["日付"][:7] for row in rows}  # "yyyy-mm"

    recent_year_months = set(sorted(year_months)[-months:]) if year_months else set()
    filtered_rows = [row for row in rows if row["日付"][:7] in recent_year_months]

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(filtered_rows)

    return out_path


def upload_processed_db() -> List[str]:
    """config/settings.yaml の drive設定を読み、data/processed/ 配下の
    アップロード対象CSVをアップロードする。
    - kakeibo_db.csv は直近 drive.recent_months か月分(デフォルト3か月)
      に絞り込んだ一時ファイルを、同じファイル名(kakeibo_db.csv)でアップロード
      (Drive容量・共有範囲を抑えるため。ローカルの全期間データは変更しない)
    - monthly_by_subcategory.csv は全期間そのままアップロード
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
    recent_months = int(drive_cfg.get("recent_months", DEFAULT_RECENT_MONTHS))

    urls = []

    db_path = Path("data/processed/kakeibo_db.csv")
    if db_path.exists():
        recent_path = Path("data/processed/.kakeibo_db_recent.csv")
        _filter_recent_months(db_path, recent_months, recent_path)
        url = upload_csv(
            recent_path, folder_id, token_path, client_secret_path,
            drive_filename="kakeibo_db.csv",
        )
        print(f"[完了] Google Driveにアップロードしました: kakeibo_db.csv(直近{recent_months}か月分) -> {url}")
        urls.append(url)
    else:
        print(f"[情報] {db_path} が無いためアップロードをスキップしました。")

    subcategory_path = Path("data/processed/monthly_by_subcategory.csv")
    if subcategory_path.exists():
        url = upload_csv(subcategory_path, folder_id, token_path, client_secret_path)
        print(f"[完了] Google Driveにアップロードしました: {subcategory_path.name} -> {url}")
        urls.append(url)
    else:
        print(f"[情報] {subcategory_path} が無いためアップロードをスキップしました。")

    return urls


if __name__ == "__main__":
    upload_processed_db()
