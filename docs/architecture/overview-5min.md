# 爆楽勤怠 AWS基盤 | 5分概要

**基準日: 2026-11-13 / 状態: 設計ドラフト・AWS基盤は未構築**

## 何を作るのか

個人学習用の勤怠Webアプリ「爆楽勤怠」。架空の社員がログインし、ワンボタンで出退勤を記録、履歴参照・後日修正・60秒以内の取消を行う。夜勤も1勤務として扱い、16時間以上の未退勤は確認するが**自動退勤しない**。別途、祝日を考慮した未退勤メール通知を実装する。

目的は単に勤怠アプリを公開することではない。**VPC、Privateサブネット、EC2、RDS、Cognito、CloudFront、Lambda、SNS、NAT EC2 + iptables を通信・権限・障害・料金まで理解すること**。本番SLAや高度な冗長化は対象外。

## 1枚で分かる構成

\`\`\`mermaid
flowchart TB
    U["ブラウザ（デモ社員）"] --> CF["CloudFront / HTTPS"]
    U -. "ログイン（OAuth2 / PKCE）" .-> COG["Cognito User Pool"]
    CF -->|"画面 /*"| S3["Private S3 / OAC"]
    CF -->|"/api/* VPC Origin<br>PoC待ち"| APP["Private EC2 / FastAPI"]
    APP -->|"5432"| DB[("Private RDS / PostgreSQL")]
    SCH["EventBridge Scheduler"] --> L["Private Lambda"]
    L -->|"5432"| DB
    L -->|"祝日API・SNSの公開Endpoint"| NAT["Public NAT EC2 / iptables SNAT"]
    NAT --> IGW["Internet Gateway / Internet"]
    L -. "SNS Publish" .-> SNS["Amazon SNS（メール）"]
\`\`\`

> 図は論理構成。SNSの実際の通信先（公開EndpointかVPC Endpointか）、SSM、NATの通信・ルーティング条件は詳細設計で扱う。Cognitoへのログインはブラウザから行い、NAT EC2は経由しない。

## サービス別の責務

| 層 | 採用・方針 | ポイント |
| --- | --- | --- |
| 画面 | Vanilla JS + Vite → 非公開S3 → CloudFront | S3への直接公開はしない。OACを使う |
| API | FastAPI → **Private EC2** | CloudFront VPC Originは**PoC後確定** |
| DB | PostgreSQL → Private RDS / Single-AZ | DBの公開IPを持たせない。SQLAlchemy/Alembic |
| 認証 | Cognito User Pool | 社員番号をusername、自己登録OFF、Authorization Code + PKCE |
| 定期処理 | EventBridge Scheduler → VPC Lambda → SNS | 土日・祝日・夜勤を考慮。外向き通信を検証 |
| 外向き通信 | Public NAT EC2 + EIP + iptables | NAT GWとの比較、故障と復旧を学習 |
| 運用 | IAM / SG / SSM / CloudWatch / Budgets | 最小権限、SSH非公開、コスト通知 |

## 現在の開発状況

- **[実装済]** ローカル/CIのFastAPI、PostgreSQL、基本打刻、取消、16時間判定、修正・監査ログ、結合テスト。mainには3テーブル（\`users\`、\`attendance_records\`、\`attendance_audit_logs\`）が存在。
- **[未実装]** Cognitoでのログイン/JWT認可、AWS実環境のVPC・EC2・RDS・S3・CloudFront、Lambda・SNS・NAT EC2の一式。GitHubのWBS 3.x・4.x・5.xが後続。
- **[要検証]** CloudFrontからPrivate EC2へ\`/api/*\`が届くか、Authorizationヘッダー/キャッシュ/HTTPS設計、NAT停止時と復旧後の挙動。
- **[未決定]** 実機で使うAZ ID、CIDR最終値、EC2/RDSサイズ、秘密情報管理、構築順序の修正、運用時間・通知対象日の細部。

## なぜこの構成か

- Private EC2 / Private RDSで外部公開面を絞り、HTTPの入口をCloudFrontへ集約する。
- NAT GatewayではなくNAT EC2を**あえて**使う。Source/Destination Check、IP forward、iptablesのFORWARD・POSTROUTING、経路表、conntrackを体験するため。管理負荷・単一障害点があるので本番推奨を意味しない。
- Single-AZ・単一API EC2・単一NATで学習費用を制御する。複数AZのサブネットはRDS DB Subnet Group用であり、アプリ全体の冗長化を意味しない。
- PostgreSQLはUTCのtimestamptzを基準にJSTで表示。日跨ぎ・同日再出勤を許可し、監査ログを同じトランザクションで記録する。

## 構築前に最優先で決めること

1. **外向き通信の導入順**: WBS 4.5でPrivate EC2を配置するのにNAT EC2は5.4の予定。初期SSM接続・パッケージ導入・Cognito JWKS取得の経路を先に確保する。
2. **CloudFront VPC Origin**: 東京対応。ただし \`apne1-az3\` は対象外。利用する実AZ IDとAPIの通信・キャッシュをPoCで確認。
3. **SG・ルートテーブル**: CloudFront→API、EC2/Lambda→RDS、Private→NAT、NAT→外部の許可を具体化。
4. **費用・停止**: Budgetsを最初に設定。RDS停止中もストレージ課金が残り、7日後に自動再起動する。NAT EC2のEIP等も確認。

**この後に読む**: [基本設計](aws-basic-design.md) → [ネットワーク詳細](aws-network-design.md) → [決定ログ](decision-log.md) → [検証計画](validation-plan.md)。進捗の正本は[GitHub Issues](https://github.com/omoy16/bakuraku-kintai/issues)。
