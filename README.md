# 爆楽勤怠（Bakuraku Kintai）

> 勤怠管理を、爆発的にラクに。

**AWSネットワーク・インフラ・Webアプリケーション開発の学習を目的とした、出退勤管理アプリの個人開発プロジェクトです。**  
会社・顧客の実データは使用せず、架空のデモユーザーで検証します。

> **開発状況：WBS 0.6 の簡易履歴一覧を実装（固定デモユーザー）。** 以下は実装予定であり、現時点で動作・公開を保証するものではありません。

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

## ローカル開発環境（WBS 0.3）

必要な環境：**Python 3.11 以上、Node.js 20.19 以上または 22.12 以上、npm**。
MVPの簡易DBはPython標準のSQLiteを使います。PostgreSQLへの移行とSQLAlchemy / Alembicの導入はWBS 1.1–1.2で行います。

### 初回セットアップ

リポジトリのルート（このREADMEがある場所）で実行します。

```bash
python -m venv .venv
```

仮想環境を有効化します。以降のPythonコマンドは有効化した環境で実行してください。

| 環境 | 有効化コマンド |
|---|---|
| Windows PowerShell | `.venv\Scripts\Activate.ps1` |
| Windows コマンドプロンプト | `.venv\Scripts\activate.bat` |
| macOS / Linux | `source .venv/bin/activate` |

PowerShellで有効化スクリプトが拒否される場合は、仮想環境のPythonを直接呼び出せます。
例えば `.venv\Scripts\python.exe -m pip install -r backend/requirements-dev.txt`、
`.venv\Scripts\python.exe dev.py api` のように実行します。

```bash
python -m pip install -r backend/requirements-dev.txt
python dev.py init-db
python dev.py test
npm --prefix frontend install
```

仮想環境はルートの `.venv/` に統一します。0.2の手順で作った `backend/.venv/` は以降使いません。
`requirements-dev.txt` はAPI実行用依存に加え、pytest / TestClient用のHTTPXをインストールします。

### 起動（ターミナルを2つ使用）

ターミナル1で仮想環境を有効化し、APIを起動します。

```bash
python dev.py api
```

ターミナル2をルートで開き、フロントエンドを起動します。Pythonは仮想環境のものを使います。

```bash
python dev.py frontend
```

ブラウザで `http://127.0.0.1:5173` を開き、勤務状態と「出勤する」または「退勤する」ボタンを確認します。
Viteは開発時 `/api/*` を `127.0.0.1:8000` にプロキシします。
停止は各ターミナルでCtrl+C。画面から出勤・退勤を打刻し、保存済みの履歴を確認できます。

### コマンドと確認先

| コマンド / URL | 内容・期待結果 |
|---|---|
| `python dev.py init-db` | SQLite初期化。既存のデータ・DBバージョンは保持 |
| `python dev.py api` | FastAPIを127.0.0.1:8000で開発起動 |
| `python dev.py test` | pytest実行。一時DBを使い、開発DBは変更しない |
| `python dev.py frontend` | Viteの開発サーバーを起動 |
| `python dev.py build` | 公開用ファイルをfrontend/dist/へ生成 |
| `http://127.0.0.1:8000/api/health` | HTTP 200 / `{"status":"ok"}` |
| `http://127.0.0.1:8000/api/health/db` | HTTP 200 / `{"status":"ok","database":"sqlite"}` |
| `http://127.0.0.1:8000/docs` | FastAPIのAPI操作画面 |

DB未初期化・接続不可・ファイル破損時、DB確認APIはHTTP 503を返します。API単体のhealthはDBとは独立しています。
DB確認APIは接続・SQLiteスキーマ読み取りを確認します。業務テーブルの存在確認や完全な整合性検査は行いません。
`dev.py` は作業ディレクトリに依存せず実行できますが、ルート以外から呼ぶ場合はスクリプトのパスを指定してください。

### 簡易DBの扱い

- 既定の保存先は `backend/data/bakuraku.sqlite3`。DBファイル・仮想環境はGit管理対象外です。
- 初期化ではSQLiteファイルと勤怠テーブル・インデックスを用意します。0.3のDBを使っている場合も、APIを停止して `python dev.py init-db` を再実行してください。既存データは保持します。
- 保存先を変える場合は環境変数 `BAKURAKU_DB_PATH` を指定します。相対パスは常にbackend/を基準とします。
- PowerShellの設定例：`$env:BAKURAKU_DB_PATH = "data/custom.sqlite3"`
- macOS / Linuxの設定例：`export BAKURAKU_DB_PATH="data/custom.sqlite3"`
- 環境変数は初期化とAPI起動の両方で同じ値にしてください。`.env` ファイルの自動読み込みは行いません。
- 開発DBを作り直す場合はAPIを停止し、必要なデータを退避してからファイルを削除し、再度 `python dev.py init-db` を実行します。

### ディレクトリ

```text
.venv/                    # 開発用Python仮想環境（Git対象外）
dev.py                    # ローカル開発コマンド
pytest.ini                # ルートからのpytest設定
backend/
  app/
    __init__.py
    main.py               # FastAPI / API・DB接続確認
    database.py           # SQLite初期化・接続
    attendance.py         # 出勤・退勤・勤務状態API
  data/                   # ローカルDB（Git対象外）
  tests/
    test_local_environment.py
    test_attendance.py
  requirements.txt        # API実行用
  requirements-dev.txt    # 開発・テスト用
frontend/
  index.html
  package.json
  vite.config.js          # 開発時APIプロキシ
  src/
    main.js               # 1ボタン打刻・勤務状態・履歴一覧・API通信
    style.css
```

## 打刻API PoC（WBS 0.4）

ユーザーは固定の `demo-user` です。リクエスト本文・ユーザー指定は不要で、打刻時刻はサーバー側のUTCで記録します。JSONの日時はUTCのISO 8601形式（末尾 `Z` または `+00:00`）です。ホーム画面では日本時間へ変換して表示します。

| メソッド | パス | 成功時 | 内容 |
|---|---|---|---|
| GET | `/api/attendance/status` | 200 | `user_id`、`status`、`active_record` |
| GET | `/api/attendance/history` | 200 | 固定デモユーザーの全打刻履歴（新しい順） |
| POST | `/api/attendance/clock-in` | 201 | 作成した勤怠レコード |
| POST | `/api/attendance/clock-out` | 200 | 退勤時刻を入れた勤怠レコード |

レコードは `id`、`user_id`、`clock_in_at`、`clock_out_at` を返します。勤務中は `clock_out_at` がnullです。
`status` は `not_working` / `working` の2種類です。勤務中だけ `active_record` にレコードが入り、それ以外はnullです。退勤後は `not_working` に戻り、同日でも次の勤務を開始できます。

- 日付で勤務を区切りません。日本時間・UTCの日付が変わっても勤務中を維持します。
- 16時間を過ぎても自動退勤しません。確認モーダルは後続WBSで追加します。
- 二重出勤は409 / `Already working`、未出勤または退勤済みの退勤は409 / `Not working` です。既存レコードは変更しません。
- サーバー時刻が出勤時刻より前に戻った場合、退勤は409 / `Clock is earlier than clock-in time` となり、勤務中を維持します。
- DB未初期化・テーブル未作成・接続不可などは503 / `Database unavailable` です。`python dev.py init-db` とDB設定を確認してください。
- 打刻の状態確認と書き込みは同一トランザクションで処理し、DBの一意制約でも「1ユーザーの勤務中レコードは最大1件」を保証します。

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

このPoCでは全アクセスが同じデモユーザーの記録を操作します。Cognito認証・ユーザー分離はWBS 3.xで追加します。取消・修正・PostgreSQLへの移行は後続WBSで扱います。

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

ホーム画面の「打刻履歴」に、固定デモユーザーの保存済みレコードを新しい順で表示します。各行には出勤日、出勤時刻、退勤時刻、勤務中／退勤済みの状態を日本時間（JST）で表示します。

- ページ表示時、手動再取得時、出勤・退勤後に `GET /api/attendance/history` から最新の履歴を取得します。
- 記録がない場合は空状態を表示し、勤務中のレコードは退勤時刻を `—` と表示します。
- 履歴取得だけが失敗した場合は一覧内にエラーを表示し、取得済みの勤務状態に基づく打刻操作は継続できます。
- この段階では全履歴を返します。ページネーション、期間絞り込み、修正・取消・変更履歴は後続WBSで扱います。

## 公開リポジトリのセキュリティ方針

AWSアクセスキー、パスワード、認証トークン、秘密鍵、実際の勤怠データ、実環境の接続情報はコミットしません。認証情報は環境変数やAWSの適切なシークレット管理手段で扱い、`.env` はコミットしない方針です。GitHub Issues・PR本文にも機密情報を記載しません。

## ステータス

**WBS 0.6：固定デモユーザーの打刻履歴API・一覧表示を実装。** 修正・取消・認証などは後続WBSで実装します。
