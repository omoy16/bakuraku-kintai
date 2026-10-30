# WBS 1.3 API構造化

> 本文はWBS 1.3時点の構造化・検証記録です。WBS 1.4でDB処理をPostgreSQLへ切り替え、user_idを数値IDへ変更しました。
> 現在の構成と手順は[WBS 1.4](postgresql-attendance-api.md)と[README](../README.md)を参照してください。

対応Issue: [#10](https://github.com/omoy16/bakuraku-kintai/issues/10)

## 目的と範囲

勤怠APIのHTTP受付、利用者と時計の取得、勤怠処理、応答の型、例外からHTTPへの変換を分ける。
WBS 1.2のSQLAlchemyモデルとAlembicは維持し、APIのPostgreSQL切替はWBS 1.4で行う。
現在のAPIはSQLite・固定デモユーザーのローカルPoCであり、認証はWBS 3.xの対象。
DBスキーマ・既存SQLiteファイル・フロントエンドの動作は変更しない。

## ファイルと役割

| app配下 | 役割 |
| --- | --- |
| `main.py` | FastAPIアプリの作成、ルーターと例外ハンドラの登録 |
| `routers/attendance.py` | 勤怠APIのURL・HTTPメソッド・応答モデル、サービスの呼び出し |
| `routers/health.py` | API単体・SQLite接続の確認 |
| `dependencies.py` | 固定利用者IDと時計関数をDependsへ供給 |
| `schemas.py` | PydanticによるAPI応答の型 |
| `attendance_service.py` | 勤務状態・履歴・出退勤の処理、SQL、トランザクションの範囲 |
| `database.py` | SQLiteの接続・初期化・commit/rollback/close、DBエラーの分類 |
| `exceptions.py` | HTTPとは独立した勤怠・DBのエラー |
| `exception_handlers.py` | 共通の409・503応答への変換 |
| `models.py` / `postgres.py` | WBS 1.2のPostgreSQL用モデルと接続。1.3では変更しない |

従来の `app.attendance` は `app.routers.attendance` と `app.attendance_service` へ分離した。
API起動先は引き続き `app.main:app` で、`python dev.py api` をそのまま使用する。

## Dependsの使い方

勤怠ルーターでは、次の宣言で利用者IDと時計を受け取る。

```python
CurrentUserId = Annotated[str, Depends(get_current_user_id)]
CurrentClock = Annotated[Callable[[], datetime], Depends(get_clock)]
```

FastAPIがリクエスト処理中に取得関数を呼ぶ。関数定義時に利用者ID・時刻を評価する初期値は使わない。
`get_current_user_id()` は今は `demo-user` を返す。
クライアントのJSONやクエリ引数から利用者ID・打刻時刻を採用しない。

`get_clock()` は現在時刻そのものではなく、現在時刻を取得する関数を返す。
サービスが `BEGIN IMMEDIATE` で書込みロックを取得して状態を確認した後に、その時計関数を呼ぶ。
ロック待ちの前に打刻時刻が確定することを避け、従来のタイミングを維持する。

テストでは以下のように差し替える。これはテスト内の設定で、外部から利用者を選ぶAPIではない。

```python
from datetime import datetime, timezone
from app.dependencies import get_clock, get_current_user_id
from app.main import app

now = datetime(2026, 10, 29, 0, 0, tzinfo=timezone.utc)
app.dependency_overrides[get_current_user_id] = lambda: "test-user"
app.dependency_overrides[get_clock] = lambda: lambda: now
try:
    # TestClient(app)からAPIを呼んで検証する
    ...
finally:
    app.dependency_overrides.clear()
```

## 維持するAPI契約

| メソッド・パス | 成功時 |
| --- | --- |
| `GET /api/health` | 200 / `{"status":"ok"}`。DBや利用者取得に依存しない |
| `GET /api/health/db` | 200 / `{"status":"ok","database":"sqlite"}` |
| `GET /api/attendance/status` | 200 / `user_id`, `status`, `active_record` |
| `GET /api/attendance/history` | 200 / 新しい順の勤怠レコード配列 |
| `POST /api/attendance/clock-in` | 201 / 作成した勤怠レコード |
| `POST /api/attendance/clock-out` | 200 / 退勤済みの同一勤怠レコード |

勤怠レコードの `id`, `user_id`, `clock_in_at`, `clock_out_at`、UTC日時、nullの扱いを維持する。
日跨ぎ・長時間勤務・同日再出勤・同時打刻の制御も既存と同じ。

## エラーとトランザクション

- 勤怠の状態不整合は `AttendanceConflictError` を送出し、共通ハンドラで409にする。
  `Already working` / `Not working` / `Clock is earlier than clock-in time` のdetailを維持する。
- DBの接続・SQL・コミット失敗などは `DatabaseUnavailableError` に分類し、共通ハンドラで503 / `Database unavailable` にする。
- DB接続・設定確認の処理は勤怠APIとDBヘルスチェックで共有する。SQLや接続先・元の例外は応答に含めない。
- 勤怠更新・応答モデル作成・commit/rollback/closeはサービス内の接続コンテキストで完了する。
  依存関数の後片付けにコミットを持たせず、コミット失敗時に成功応答を先に返さない。
- 設定のValueErrorはDBエラーに分類するが、勤怠処理やPydantic変換の予期しないValueErrorは503へ変換しない。
  プログラムの不具合として500にし、書込みはロールバックする。
- FastAPI標準の404・入力検証などの処理は共通ハンドラで上書きしない。

## 検証と再実行

2026-10-29（JST）のローカル検証はPython 3.12.14で **47 passed / 26 skipped**。
PostgreSQL接続先がないため、WBS 1.2の実DBテスト26件のみskipした。
追加9件では利用者のリクエスト単位の切り替え、全勤怠操作への受け渡し、外部入力による利用者・時刻の上書き防止、
ロック後の時計読み取り、共通503、更新後の失敗時のロールバック、プログラム不具合の500、healthの独立性、OpenAPIを検証した。
Viteの本番ビルドも成功した。Starlette/httpxの既存の非推奨警告が1件ある。

```bash
python -m pip install -r backend/requirements-dev.txt
python dev.py test
npm --prefix frontend ci
python dev.py build
```

CIの `pytest` ジョブはPython 3.11 / PostgreSQL 16で実DBテストを含めて実行する。
`poc-e2e` ジョブはChromium → Vite → FastAPI → 一時SQLiteの既存ブラウザ試験11件を実行する。
当該コミットの実行結果・証跡へのリンクは対応PRに記録する。

ブラウザ試験を手元で再実行する場合は、開発API・Viteを停止し、8000番・5173番ポートを空けてから実行する。

```bash
python -m pip install -r backend/requirements-e2e.txt
npm --prefix frontend ci
python -m playwright install chromium
python -m pytest tests/e2e -q
```

今回のローカル環境ではChromiumのダウンロードが破損アーカイブとなり、システムパッケージの導入も権限不足のため、
ブラウザ試験は実行できなかった。CIでの結果はローカルの結果と区別してPRに記録する。
詳細な試験内容は [PoC結合試験](poc-integration-test.md) を参照。

## 完了判断

APIRouter・Depends・Pydantic・例外共通処理の整理に加え、当該PRのCIと確認記録を確認する。
Issue #10のクローズは、検証済みPRがmainへマージされた時点で行う。
