# 爆楽勤怠（Bakuraku Kintai）

> 勤怠管理を、爆発的にラクに。

**AWSネットワーク・インフラ・Webアプリケーション開発の学習を目的とした、出退勤管理アプリの個人開発プロジェクトです。**  
会社・顧客の実データは使用せず、架空のデモユーザーで検証します。

> **開発状況：WBS 0.2 の雛形実装済み（業務機能は未実装）。** 以下は実装予定であり、現時点で動作・公開を保証するものではありません。

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

## ローカル起動手順（WBS 0.2 雛形）

必要な環境：**Python 3.11 以上、Node.js 20.19 以上または 22.12 以上、npm**。以下は暫定手順で、仮想環境・pytest・簡易DBなどの本格的な整備は WBS 0.3 以降に行います。

### バックエンド（ターミナル1）

```bash
cd backend
python -m venv .venv
# Windows PowerShell: .venv\Scripts\Activate.ps1
# Linux / macOS: source .venv/bin/activate
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

`http://127.0.0.1:8000/api/health` が `{"status":"ok"}` を返すことを確認します。

### フロントエンド（ターミナル2）

```bash
cd frontend
npm install
npm run dev
```

`http://127.0.0.1:5173` にアクセスします。Viteは開発時 `/api/*` を `127.0.0.1:8000` にプロキシします。画面にはAPIの接続状態のみ表示され、**打刻・履歴は未実装**です。

公開用ファイルは `cd frontend && npm run build` で `frontend/dist/` に生成されます。AWS環境のAPIルーティング・認証は後続WBSで確認します。

### ディレクトリ

```text
backend/
  app/
    __init__.py
    main.py          # FastAPI
  requirements.txt
frontend/
  index.html
  package.json
  vite.config.js     # 開発時APIプロキシ
  src/
    main.js          # 最小画面
    style.css
```

## 公開リポジトリのセキュリティ方針

AWSアクセスキー、パスワード、認証トークン、秘密鍵、実際の勤怠データ、実環境の接続情報はコミットしません。認証情報は環境変数やAWSの適切なシークレット管理手段で扱い、`.env` はコミットしない方針です。GitHub Issues・PR本文にも機密情報を記載しません。

## ステータス

**WBS 0.2：FastAPI / Vite の雛形を実装。** 打刻、履歴、DB、認証などの業務機能は今後実装します。
