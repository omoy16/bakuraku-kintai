# 爆楽勤怠（Bakuraku Kintai）

> 勤怠管理を、爆発的にラクに。

**AWSネットワーク・インフラ・Webアプリケーション開発の学習を目的とした、出退勤管理アプリの個人開発プロジェクトです。**  
会社・顧客の実データは使用せず、架空のデモユーザーで検証します。

> **開発状況：WBS 1.4のPostgreSQL打刻APIを実装（固定デモユーザー）。** AWS実環境・認証・取消・修正は後続WBSで確認します。

## アプリの主な機能（予定）

- **ワンボタン打刻**：未出勤なら「出勤する」、勤務中なら「退勤する」を表示。日付が変わっても勤務中の状態を維持。
- **勤怠履歴**：日々の出退勤記録を一覧表示。
- **打刻修正・変更履歴**：自分の記録を修正し、変更前後の時刻と修正日時を確認。
- **60秒以内の打刻取消**：押し間違いをサーバー側で期限確認して取り消す。
- **長時間勤務の確認**：出勤から16時間以上で未退勤なら、「まだ勤務中ですか？」と確認。自動退勤はしない。
- **未退勤通知**：Lambdaが休日・夜勤を考慮して確認し、必要に応じてSNSメールを送信。

UIは、**シンプルな文字とオレンジの炎リング＋明るいブルー**を基調とするC案を採用予定です。

## 技術スタック（予定）

| 領域 | 技術 |
|---|---|
| フロントエンド | HTML / CSS / JavaScript（Vite）、S3、CloudFront |
| バックエンド | Python 3.11+、FastAPI、Pydantic、SQLAlchemy、Alembic |
| データベース | PostgreSQL / Amazon RDS |
| 認証 | Amazon Cognito（Authorization Code + PKCE、JWT検証） |
| 定期処理 | AWS Lambda、EventBridge Scheduler、Amazon SNS |
| ネットワーク | VPC、EC2、Security Group、NAT EC2、iptables、IGW |
| 開発・テスト | GitHub Issues、Pull Requests、pytest、GitHub Actions |

## AWS構成（計画）

```text
利用者ブラウザ
   └── CloudFront (HTTPS)
         ├── /      → 非公開 S3 (OAC) → フロントエンド
         └── /api/* → VPC Origin (技術検証予定)
                            └── Private EC2 / FastAPI
                                    └── Private RDS / PostgreSQL

Private Subnet: Lambda (EventBridge Scheduler)
   ├── RDS にアクセス（勤怠の確認）
   └── NAT EC2 (Public Subnet, iptables)
           └── Internet Gateway → 祝日APIなど外部サービス / SNS API
```

この構成は学習用の候補です。**CloudFront VPC Originの要件・通信経路はPoCで確認してから確定**します。NAT EC2はLinuxネットワーク学習用であり、可用性・運用負荷の観点から本番向けの推奨構成とは限りません。

## WBS / 開発管理

- [全45タスクのGitHub Issues](https://github.com/omoy16/bakuraku-kintai/issues)
- [WBS・予定日・Issue対応表](docs/WBS.md)
- [Pull Requests](https://github.com/omoy16/bakuraku-kintai/pulls)

**GitHub Issuesがタスクの進捗管理の正本**です。WBSは予定の索引として使用します。

- **MVP (Day 1–2)：** ローカルで出勤 → 退勤 → 履歴確認
- **API/DB (Day 3–6)：** PostgreSQL、取消、修正、テスト
- **UI (Day 6–8)：** C案の画面、確認・修正モーダル
- **Cognito (Day 8–10)：** 認証とユーザー分離
- **AWS (Day 10–13)：** VPC、EC2、RDS、S3、CloudFront
- **通知/NAT (Day 13–16)：** Lambda、外部祝日API、SNS、NAT EC2
- **総合試験 (Day 16–18)：** 機能・セキュリティ・費用評価

計画工数は**ユーザー実働137時間**（予備日2日を別途想定）。ChatGPTは設計・実装・テスト・レビューを支援します。

## ローカル開発環境（WBS 1.4）

必要な環境：Python 3.11以上、Node.js 20.19以上または22.12以上、npm、PostgreSQL 16。
ローカルDBは既存の `compose.yaml` で起動できます。ルートの `.venv/` を使用します。

### 初回セットアップ（Windows PowerShell）

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r backend/requirements-dev.txt
npm --prefix frontend ci

$env:BAKURAKU_POSTGRES_PASSWORD = "your-local-password"
docker compose up -d postgres
docker compose ps

$env:BAKURAKU_DATABASE_URL = "postgresql+psycopg://bakuraku:your-local-password@127.0.0.1:5432/bakuraku"
python dev.py init-db
python dev.py seed-demo
```

PostgreSQLがhealthyになってからinit-dbを実行します。パスワードはローカル用に置き換え、
接続URLでは必要に応じてURLエンコードしてください。`.env`の自動読み込みは行いません。
仮想環境の有効化が拒否される場合、`.venv\Scripts\python.exe dev.py api`のように直接実行できます。
macOS/Linuxでは仮想環境を `source .venv/bin/activate`、環境変数を `export` で設定します。

init-dbはAlembicでPostgreSQLのスキーマを作成・更新します。seed-demoはデモ利用者を明示登録します。
どちらも再実行可能です。利用者IDはDBの生成値を使い、1とは仮定しません。
API起動・マイグレーションでは利用者を自動登録しません。

### 起動（ターミナルを2つ使用）

API側のターミナルでは同じ `BAKURAKU_DATABASE_URL` を設定してください。

```powershell
python dev.py api
```

もう一方のターミナルでフロントエンドを起動します。

```powershell
python dev.py frontend
```

ブラウザで `http://127.0.0.1:5173` を開きます。Viteは `/api/*` をFastAPIへ転送します。
停止は各ターミナルでCtrl+C。`http://127.0.0.1:8000/docs`ではAPIを操作できます。

### コマンドと確認先

| コマンド / URL | 内容 |
| --- | --- |
| `python dev.py init-db` | PostgreSQLのAlembicマイグレーション |
| `python dev.py seed-demo` | local:demo-userの明示登録・生成IDの表示 |
| `python dev.py api` | APIを127.0.0.1:8000で開発起動 |
| `python dev.py test` | pytest。実DB試験にはテスト用URLを明示 |
| `python dev.py frontend` | Viteを起動 |
| `python dev.py build` | frontend/dist/へビルド |
| `/api/health` | 200 / `{"status":"ok"}`。DBなしでも利用可能 |
| `/api/health/db` | 200 / `{"status":"ok","database":"postgresql"}` |

DB接続確認はSELECT 1を実行します。マイグレーション・デモ登録の完了確認ではありません。
URL未設定・不正、接続不可などではDB依存APIが503になります。APIはSQLiteへ自動切替しません。
デモユーザーが未登録の場合も、勤怠APIは503です。init-dbとseed-demoを確認してください。

### 既存SQLiteの扱い

WBS 0.xのSQLiteファイルは保持します。PostgreSQLへの自動変換・コピー・削除は行いません。
現在のAPIとinit-dbはSQLiteを使用しません。旧 `BAKURAKU_DB_PATH` だけではAPIを起動・初期化できません。
移行が必要な場合は別途方針を決めます。[PostgreSQL打刻APIの設計と検証](docs/postgresql-attendance-api.md)も参照してください。

### 主な構成

| ファイル | 担当 |
| --- | --- |
| `backend/app/main.py` | アプリ・Engineの寿命・ルーターと例外ハンドラ登録 |
| `backend/app/routers/` | 勤怠とヘルスチェックのHTTP受付 |
| `backend/app/dependencies.py` | DB Engine・生成利用者ID・時計の供給 |
| `backend/app/attendance_service.py` | 行ロック・勤怠更新・操作ログ |
| `backend/app/postgres.py` | PostgreSQL接続・トランザクション・DBエラー分類 |
| `backend/app/models.py` / `schemas.py` | DBモデル / API応答の型 |
| `backend/app/database.py` | 旧SQLite PoC用ヘルパー（現APIでは未使用） |
| `frontend/src/main.js` | ワンボタン打刻・勤務状態・履歴・API通信 |

## 打刻API（WBS 1.4）

ユーザーは明示seedした `local:demo-user` に対応する生成利用者IDです。リクエスト本文・ユーザー指定は不要で、打刻時刻はサーバー側のUTCで記録します。JSONの日時はUTCのISO 8601形式（末尾 `Z` または `+00:00`）です。ホーム画面では日本時間へ変換して表示します。

| メソッド | パス | 成功時 | 内容 |
|---|---|---|---|
| GET | `/api/attendance/status` | 200 | `user_id`、`status`、`active_record` |
| GET | `/api/attendance/history` | 200 | 明示seedしたデモユーザーの全打刻履歴（新しい順） |
| POST | `/api/attendance/clock-in` | 201 | 作成した勤怠レコード |
| POST | `/api/attendance/clock-out` | 200 | 退勤時刻を入れた勤怠レコード |

レコードは `id`、`user_id`、`clock_in_at`、`clock_out_at` を返します。`user_id`は旧PoCの文字列からJSON整数へ変更しました。勤務中は `clock_out_at` がnullです。
`status` は `not_working` / `working` の2種類です。勤務中だけ `active_record` にレコードが入り、それ以外はnullです。退勤後は `not_working` に戻り、同日でも次の勤務を開始できます。

- 日付で勤務を区切りません。日本時間・UTCの日付が変わっても勤務中を維持します。
- 16時間を過ぎても自動退勤しません。確認モーダルは後続WBSで追加します。
- 二重出勤は409 / `Already working`、未出勤または退勤済みの退勤は409 / `Not working` です。既存レコードは変更しません。
- サーバー時刻が出勤時刻より前に戻った場合、退勤は409 / `Clock is earlier than clock-in time` となり、勤務中を維持します。
- DB未初期化・テーブル未作成・接続不可などは503 / `Database unavailable` です。`python dev.py init-db` とDB設定を確認してください。
- 打刻は利用者行→勤怠行の順にロックし、勤怠と操作ログを同一トランザクションで保存します。DBの部分一意・排他制約でも二重出勤と時間重複を防ぎます。
- 時間重複は409 / `Attendance period overlaps existing record`、操作ログの保存・コミット失敗も全体をロールバックして503になります。

### 手動確認（PowerShell）

初回セットアップまたは更新後のDB初期化を済ませ、`python dev.py api` を起動します。別ターミナルで順番に実行してください。

```powershell
$base = "http://127.0.0.1:8000"
Invoke-RestMethod "$base/api/attendance/status"
Invoke-RestMethod -Method Post "$base/api/attendance/clock-in"
Invoke-RestMethod "$base/api/attendance/status"
Invoke-RestMethod -Method Post "$base/api/attendance/clock-out"
Invoke-RestMethod "$base/api/attendance/status"
Invoke-RestMethod "$base/api/attendance/history"
```

状態が `not_working → working → not_working` になることと、出退勤で同じレコードIDが返ることを確認します。
出勤後にAPIをCtrl+Cで停止・再起動しても `working` が残ることを確認できます。
ブラウザの `http://127.0.0.1:8000/docs` からも各APIを実行できます。Vite起動中は `http://127.0.0.1:5173/api/attendance/status` でも状態を取得できます。

現在は全アクセスが同じデモユーザーの記録を操作するローカル用APIです。Cognito認証・ユーザー分離はWBS 3.x、取消・修正は後続WBSで扱います。

## 簡易ホームUI（WBS 0.5）

`http://127.0.0.1:5173` のホーム画面で出勤・退勤を打刻できます。オレンジのリングと読みやすい文字、青を基調にした簡易UIです。デザインの最終調整はWBS 2.xで行います。

- ページ表示時に勤務状態をAPIから取得し、勤務外は青い「出勤する」、勤務中はオレンジの「退勤する」を表示します。「勤務外」は未出勤・退勤後の両方を含みます。
- 日付・現在時刻・勤務中の出勤時刻は日本時間（JST）で表示します。画面の現在時刻はブラウザの時計、実際の打刻時刻はサーバーの時計です。
- 打刻後はAPIから最新状態を取得します。再読み込み時もAPIの勤務状態を復元します。
- 通信中は打刻・再確認ボタンを無効にします。状態取得に失敗したときも打刻できず、「状態・履歴を再確認」で復旧を試せます。
- 通信は10秒でタイムアウトします。打刻応答が不明なとき、アプリからPOSTを自動再送せず、GETで状態を確認します。409でも最新状態を取得し直します。
- 日跨ぎでも勤務中のままです。未退勤確認・取消・認証は後続WBSで追加します。

### 画面からの確認手順

1. `python dev.py init-db` を実行し、2つのターミナルで `python dev.py api` と `python dev.py frontend` を起動します。
2. ホーム画面を開き、「勤務外」「出勤する」を確認します。既に勤務中の記録がある場合は「退勤する」から始まります。
3. 「出勤する」を押し、「勤務中」「退勤する」と出勤時刻、勤務中の履歴が表示されることを確認します。
4. ブラウザを再読み込みし、勤務中の状態・出勤時刻が残ることを確認します。
5. 「退勤する」を押し、「勤務外」「出勤する」と退勤の完了メッセージ、履歴の退勤時刻を確認します。
6. APIを停止し、「状態・履歴を再確認」を押してエラー表示・打刻不可を確認します。API再起動後に再確認し、復旧することを確認します。

## 簡易履歴一覧（WBS 0.6）

ホーム画面の「打刻履歴」に、明示seedしたデモユーザーの保存済みレコードを新しい順で表示します。各行には出勤日、出勤時刻、退勤時刻、勤務中／退勤済みの状態を日本時間（JST）で表示します。

- ページ表示時、手動再取得時、出勤・退勤後に `GET /api/attendance/history` から最新の履歴を取得します。
- 記録がない場合は空状態を表示し、勤務中のレコードは退勤時刻を `—` と表示します。
- 履歴取得だけが失敗した場合は一覧内にエラーを表示し、取得済みの勤務状態に基づく打刻操作は継続できます。
- この段階では全履歴を返します。ページネーション、期間絞り込み、修正・取消・変更履歴は後続WBSで扱います。

## ブラウザ結合試験（WBS 0.7 → 1.4）

既存のPC/スマホ幅・出退勤・履歴・再読み込み・API再起動・通信障害・409・連打・JST表示の11件を、
Chromium → Vite → FastAPI → 一時PostgreSQLスキーマで検証します。
WBS 0.7当時のSQLite結果は[過去の検証記録](docs/poc-integration-test.md)に残しています。

API・Viteを停止し、8000番・5173番ポートを空けて実行してください。
`BAKURAKU_TEST_DATABASE_URL`はテスト専用DBの接続先を明示します。未設定時、実DB試験はskipされます。

```powershell
docker compose exec postgres createdb -U bakuraku bakuraku_test
$env:BAKURAKU_TEST_DATABASE_URL = "postgresql+psycopg://bakuraku:your-local-password@127.0.0.1:5432/bakuraku_test"
python -m pip install -r backend/requirements-e2e.txt
python -m playwright install chromium
python dev.py test
python -m pytest tests/e2e -q
```

createdbはテストDBが未作成の場合だけ実行します。試験はランダム名の専用スキーマを使い、終了時に片付けます。
ブラウザ試験ではAPI・Viteの起動停止とDB初期化・seedを自動で行い、開発DB・既存SQLiteは変更しません。
通常の `python dev.py test` にPlaywrightは不要です。CIはPostgreSQL実DB試験とブラウザ試験を別ジョブで実行します。

## PostgreSQL・SQLAlchemy・Alembic（WBS 1.2）

PostgreSQL 16用の3テーブルモデル、UTC接続、Alembic初期マイグレーション、実DBテストを追加しました。#8のDB設計と修正理由 `change_reason` の補足を反映しています。[起動・マイグレーション・データ移行方針・検証手順](docs/postgresql-setup.md)を参照してください。

WBS 1.4（#11）でAPI・DB接続確認・init-dbをPostgreSQLへ切り替えました。現在の起動手順は本READMEを参照してください。

## API構造化（WBS 1.3）

勤怠・ヘルスチェックをAPIRouterで分け、利用者IDと時計をDependsで受け取る構成に整理しました。
勤怠処理は `attendance_service.py`、API応答の型は `schemas.py`、409・503への変換は共通例外ハンドラが担当します。
勤怠の更新・コミット・ロールバック・接続解放はサービス内で完了します。
時計は時刻そのものではなく関数を渡すため、DBの書込みロック取得後にサーバー時刻を読み取ります。

1.3時点ではSQLite PoCの応答を維持しました。1.4でPostgreSQLへ切り替え、user_idを生成された数値IDへ変更しています。JWT認証はWBS 3.xの対象です。
[構成・Dependsの差し替え例・確認手順](docs/api-structure.md)を参照してください。

## 公開リポジトリのセキュリティ方針

AWSアクセスキー、パスワード、認証トークン、秘密鍵、実際の勤怠データ、実環境の接続情報はコミットしません。認証情報は環境変数やAWSの適切なシークレット管理手段で扱い、`.env` はコミットしない方針です。GitHub Issues・PR本文にも機密情報を記載しません。

## ステータス

**WBS 1.4：PostgreSQLによる打刻・監査ログ・同時実行制御を実装。** 最終コミットの検証結果は対応PRに記録します。修正・取消・認証は後続WBSの対象です。
