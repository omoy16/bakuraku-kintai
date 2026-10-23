# 爆楽勤怠（Bakuraku Kintai）

> 勤怠管理を、爆発的にラクに。

**AWSネットワーク・インフラ・Webアプリケーション開発の学習を目的とした、出退勤管理アプリの個人開発プロジェクトです。**  
会社・顧客の実データは使用せず、架空のデモユーザーで検証します。

> **開発状況：WBS 0.3 のローカル開発環境を整備（業務機能は未実装）。** 以下は実装予定であり、現時点で動作・公開を保証するものではありません。

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

ブラウザで `http://127.0.0.1:5173` を開き、**API：接続OK**を確認します。
Viteは開発時 `/api/*` を `127.0.0.1:8000` にプロキシします。
停止は各ターミナルでCtrl+C。打刻・履歴はWBS 0.4以降に実装します。

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
- 初期化ではSQLiteファイルだけを用意します。勤怠テーブルはWBS 0.4で追加します。
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
  data/                   # ローカルDB（Git対象外）
  tests/
    test_local_environment.py
  requirements.txt        # API実行用
  requirements-dev.txt    # 開発・テスト用
frontend/
  index.html
  package.json
  vite.config.js          # 開発時APIプロキシ
  src/
    main.js               # 最小画面
    style.css
```

## 公開リポジトリのセキュリティ方針

AWSアクセスキー、パスワード、認証トークン、秘密鍵、実際の勤怠データ、実環境の接続情報はコミットしません。認証情報は環境変数やAWSの適切なシークレット管理手段で扱い、`.env` はコミットしない方針です。GitHub Issues・PR本文にも機密情報を記載しません。

## ステータス

**WBS 0.3：仮想環境・pytest・SQLite・起動コマンドを整備。** 打刻、履歴、認証などの業務機能は今後実装します。
