# 爆楽勤怠 | AWS基盤基本設計

- **版**: 2026-11-13 設計統合ドラフト
- **対象**: 学習・デモ用のAWS東京リージョン（ap-northeast-1）
- **ステータス**: アプリ・DBの一部はローカル/CI実装済み。AWS実機構築・料金確定・障害試験は未実施
- **注意**: 実会社データ、秘密情報、AWSのアカウント識別子、通知先実メールアドレスなどは公開文書に記載しない

最初に[5分概要](overview-5min.md)、その後[ネットワーク詳細](aws-network-design.md)、[判断ログ](decision-log.md)、[検証計画](validation-plan.md)を参照。

## 1. 目的・範囲

勤怠Webアプリ「爆楽勤怠」を題材に、VPC、Public/Private Subnet、EC2、RDS、S3、CloudFront、Cognito、VPC Lambda、EventBridge Scheduler、SNS、NAT EC2とiptables、IAM/SSM/SGの関係を、実機で構築・確認する学習プロジェクト。

| 対象 | 今回の対象外 |
| --- | --- |
| 架空の複数社員でログイン・本人の勤怠のみ操作 | 実会社データ、給与計算、休暇申請、管理者承認 |
| ワンボタン打刻、夜勤、同日再出勤、履歴、後日修正、取消 | 管理者画面、本人の自己登録 |
| 16時間以上未退勤の本人確認（自動退勤なし） | 本番SLA、高負荷、オートスケール |
| 祝日API、Lambda、SNSによる未退勤通知 | Multi-AZ RDS、本番NAT GW常設、ALB冗長化 |
| NAT EC2の経路・SNAT・停止/復旧・料金比較 | 本番の可用性設計そのもの |

設計優先順位は**学習価値、正しい通信・権限の理解、低コスト、シンプルな構成**。単一障害点の存在を隠さず試験する。

## 2. 構成と採用理由

\`\`\`mermaid
flowchart LR
    U["ブラウザ"] -->|"HTTPS"| CF["CloudFront"]
    U -. "CognitoでPKCEログイン" .-> C["Cognito User Pool"]
    CF -->|"/*"| S3["S3（非公開/OAC）"]
    CF -->|"/api/*: VPC OriginをPoC"| A["Private EC2 / FastAPI"]
    A -->|"TCP 5432"| DB[("Private RDS / PostgreSQL")]
    EV["EventBridge Scheduler"] --> L["Private Lambda"]
    L -->|"TCP 5432"| DB
    L -->|"外向きHTTPS"| N["Public NAT EC2"]
    N --> IGW["IGW → Internet"]
    L -. "SNS Publish" .-> S["SNS → Email"]
\`\`\`

| 層 | リソース | 設計方針と理由 |
| --- | --- | --- |
| CDN | CloudFront | HTTPS入口を統合し、Web画面とAPIをパスで分離 |
| フロント | 非公開S3 + OAC | S3を直接公開せずVite成果物を配信 |
| API | Private EC2 + FastAPI | Public IPなし。CloudFront VPC OriginでAPI到達をPoC |
| DB | Amazon RDS PostgreSQL、Single-AZ | 専用のPrivate DB、SQLAlchemy/Alembicを利用 |
| 認証 | Cognito User Pool | パスワードをアプリで保持せずJWTを検証 |
| バッチ | EventBridge Scheduler + VPC Lambda | 定期的な未退勤・祝日判定 |
| 通知 | Amazon SNS Email | 未退勤をメール通知（送達保証と重複抑止は要検証） |
| NAT | Public NAT EC2 + EIP | NAT GWではなくSNAT/IP Forward/conntrackを学ぶ |
| 管理 | IAM/SG/SSM/CloudWatch/Budgets | 最小権限、鍵レス管理、証跡、費用監視 |

**構築済みではない**点に注意。WBS 4.x、5.xはGitHub Issueで未完了。基本的なAPI・DBコードはmainに存在する。

### 2.1 CloudFrontの二つのオリジン

- Default（画面）: S3 RESTオリジン + Origin Access Control、S3 Block Public Access有効。S3静的Webサイト公開は使わない。
- API（/api/*）: Private EC2へCloudFront VPC Origin。APIのキャッシュは無効にし、Authorizationヘッダー、Content-Type、必要なHTTPメソッドを転送する。実挙動はWBS 4.7で検証。
- ブラウザ→CloudFrontはHTTPS。**CloudFront→EC2がHTTPかHTTPSかは未確定**。旧案にはHTTPオリジンのPoC想定があり、E2E TLSを保証するものではない。証明書・DNS・TLS終端を検証する。
- AWS公式によれば東京リージョンはVPC Origin対応。ただしAZ ID **apne1-az3は除外**。AZ名だけでなく実際のAZ IDを確認する。
- CloudFront VPC Originが期待どおり動かなければ、代替入口をWBS 4.7に記録して再設計する。ALBの追加は確定していない。

### 2.2 PrivateサブネットとRDS

- VPCは東京に1つ、Public 1つ/Private 2つ（別AZ）を計画。CIDRは以前の設計例があるが、AWSコンソールの最終設定値ではない。
- API EC2とLambdaはRDSにVPC内経路で接続するため、**RDS宛の通信にはNATが不要**。
- RDSはPublicly accessible=false、DB Subnet Groupは異なるAZのPrivate Subnetに配置。これはDBサブネットの要件を満たすためで、RDSをMulti-AZにする意味ではない。
- EC2/Lambda→RDSはTCP 5432と必要なSGに絞る。DB認証情報の保管先、TLS、拡張機能の導入権限はWBS 4.4で確定。

### 2.3 NAT EC2

- Public SubnetにNAT用EC2を1台、必要ならEIPを割り当てる。
- Source/Destination Check無効化、Linuxのnet.ipv4.ip_forward=1、FORWARD許可、natテーブルのPOSTROUTING/MASQUERADEを設定・永続化。
- Privateの0.0.0.0/0の経路をNAT EC2のENI等へ設定。NAT EC2の外向き0.0.0.0/0はIGW。
- NATの停止、iptablesルール削除、復旧の各段階で通信・カウンタ・CloudWatch・SGを比較。
- NAT Gatewayより必ず安いとは断定しない。インスタンス、EBS、IPv4、転送、稼働時間、運用負荷まで比較する。
- **設計上の依存関係に注意**: 現WBSではPrivate EC2の配置が4.5、NAT EC2が5.4。SSM、パッケージ導入、Cognito公開JWKSなどに外向き通信が必要なため、NAT構築を前倒すかVPC Endpoint等の初期管理経路を用意する。順番は未変更。

## 3. 認証・認可

### 3.1 ブラウザ/Cognito

- Cognito User Poolのサインイン識別子は**username（架空の社員番号）**。例: 000001。
- **自己登録無効**。デモ社員は管理者がCognitoに追加。アプリ内管理者機能は作らない。
- Authorization Code Flow + PKCE（S256）。公開Webクライアントでclient secretは使わない。
- Vanilla JavaScript/Viteを継続し、Web Crypto APIとCognitoの標準OAuthエンドポイントを使う。Amplify、oidc-client-ts、React、追加のフロントルーターは採用しない（[WBS 3.2](https://github.com/omoy16/bakuraku-kintai/issues/24)）。
- Callback URL、state/nonce、認証コード交換、token保管・破棄、期限切れ処理は実装時に検証。認証トークンを公開ログやリポジトリに残さない。

### 3.2 FastAPI/JWT/DB

\`\`\`text
ブラウザ -- Cognito認証 --> アクセストークン
ブラウザ -- Authorization: Bearer ... --> CloudFront /api/* --> FastAPI
FastAPI -- JWKSを利用して署名・claims検証 --> Cognito sub
FastAPI -- users.cognito_subを照合 --> users.id → 本人の勤怠のみ操作
\`\`\`

FastAPIでJWT署名、iss、exp、token_use=access、client_id、kid/JWKSキャッシュ（必要に応じてscope）を検証する。URLやJSONに送られた任意のuser_idは権限の根拠としない。[WBS 3.3](https://github.com/omoy16/bakuraku-kintai/issues/25)、[3.4](https://github.com/omoy16/bakuraku-kintai/issues/26)。

- 既存PostgreSQLのusers.cognito_subはUNIQUEで、社員番号より永続的な内部識別子として使う。
- 初回APIアクセス時にDBユーザーを作る案は過去に検討。競合・退職・再登録・User Pool分離やローカルデモユーザーとの移行は**未決定**。
- 現状のローカル固定デモユーザーはAWS Cognito連携が完了していることを意味しない。
- CognitoのJWKS公開URLをPrivate EC2が取得する場合の外向き通信は、初期管理経路と併せて設計する。

## 4. アプリ・DBの現状（AWSへ移設する対象）

### 4.1 技術スタック

| 機能 | 現状 |
| --- | --- |
| フロント | HTML/CSS/Vanilla JS + Vite |
| API | Python 3.11+、FastAPI、APIRouter、Depends、Pydantic |
| DB | PostgreSQL、SQLAlchemy、Alembic |
| EC2運用 | Uvicorn + systemdの予定。OS/AMI/サイズは未確定 |
| CI | GitHub ActionsのPostgreSQLを用いてテスト。AWS実機はまだ |

### 4.2 3つのDBテーブル

| テーブル | 意味 | 主なカラム |
| --- | --- | --- |
| users | 利用者 | id、cognito_sub（UNIQUE）、display_name |
| attendance_records | 勤怠単位・通知/未退勤確認 | user_id、clock_in_at、clock_out_at、cancelled_at、reminder_sent_at、overdue_confirmed_at、overdue_confirmed_choice |
| attendance_audit_logs | 操作履歴・修正理由 | attendance_record_id、actor_user_id、operation、before_values、after_values、change_reason |

- 旧設計のnotification_log・work_date・「1日1行」方式は不採用。
- 同日再出勤、日跨ぎを許可。出退勤時刻はPostgreSQL timestamptzで扱い、表示/検索はAsia/Tokyoへ変換。
- 有効な勤務中は1ユーザーにつき最大1件、勤務時間の重複を排他制約で拒否。二重打刻等は409。
- 出勤取消は削除せずcancelled_atで保持。退勤取消はclock_out_atをNULLに戻す。取消はサーバー記録の操作日時から60秒以内。
- 更新と監査ログは同じトランザクション。ログ保存失敗時は更新もロールバック。
- 16時間以上未退勤は本人確認。自動退勤なし。再表示抑制は現行APIで暫定1時間。
- 具体的な列・制約は[models.py](../../backend/app/models.py)、[Issue #8](https://github.com/omoy16/bakuraku-kintai/issues/8)、Alembicマイグレーションを参照。

## 5. Lambda / 祝日API / SNS

\`\`\`mermaid
flowchart TD
  T["Scheduler定期起動"] --> L["VPC Lambda"]
  L --> H["祝日API (NAT EC2経由)"]
  H --> V{"休日・対象日を確実に判断できる?"}
  V -- いいえ --> B["通知中止/保留しログ"]
  V -- はい --> R["RDSから未退勤候補取得"]
  R --> S{"既に通知成功済み?"}
  S -- はい --> X["スキップ"]
  S -- いいえ --> N["SNS Publish"]
  N --> A["成功時reminder_sent_atを記録"]
\`\`\`

- EventBridge Schedulerの**毎朝09:00 JST**は2026-10の旧ドラフト値。現時点で確定した時刻ではない。
- Holidays JP APIを祝日判定の候補とする。外部データに欠損・通信失敗・JSON不正がある場合は、誤通知しないよう保留/中止。
- 未退勤の対象日は土日・祝日・夜勤・連休明けを踏まえてWBS 5.2で確定する。
- SNSのPublish成功はメール到着成功と同義ではない。reminder_sent_atはSNS受付後の記録で、実メール受信を保証しない。
- 同時Lambda実行、SNS成功後DBコミット前の停止、SNS受付結果不明時には厳密な一回通知を保証できない。排他・再試行の仕様をWBS 5.3で設計する。
- SNS APIの外向きアクセスは今回はNAT EC2経路を使う計画。将来のSNS VPC Endpointとは切り分ける。

## 6. セキュリティと運用

| 観点 | 基本設計 | 未完の検証 |
| --- | --- | --- |
| S3 | Block Public Access + OAC | URL直接アクセス不可 |
| DB | RDS非公開、sg-app/sg-lambdaのみ5432 | 直接アクセス不可、DB権限/TLS |
| API | VPC Origin、キャッシュ無効、JWT検証 | 署名偽装、期限切れ、IDOR |
| EC2管理 | SSH/22を公開しない。SSM Session Managerを想定 | Agent/IAM/外向き経路 |
| 秘密情報 | 環境変数/マネージドシークレット保管を検討、Gitに置かない | 保管方式の決定とローテーション |
| 監視 | CloudWatch Logs、Lambda失敗、EC2異常、RDS容量、NAT疎通 | ログ保持期間/通知 |
| バックアップ | RDS自動バックアップの有効化を検討 | 保持期間、復元試験 |
| コスト | Budgets、タグ、検証時のみ稼働 | 停止・削除後の残存請求 |

停止案: Scheduler無効化 → 実行中処理の終了確認 → アプリEC2 → NAT EC2 → RDS。再開案: RDS → NAT EC2 → アプリEC2 → 全疎通 → Scheduler再有効化。

**RDSは停止してもストレージ等の課金が残り、連続7日停止で自動再起動**する（[AWS公式](https://docs.aws.amazon.com/ja_jp/AmazonRDS/latest/UserGuide/USER_StopInstance.html)）。EBS、IPv4/EIP、CloudWatch Logs、バックアップの残存も確認する。

AWS変更・障害試験は**変更前の観測項目とコマンド結果→変更→同じ観測項目を変更後に取得**し、差分を記録する。[検証計画](validation-plan.md)で一覧化。

## 7. 未解決と次の判断

1. **最優先**: Private EC2の初期外向き経路/SSMを、WBS 5.4 NAT EC2構築より先にどう用意するか。
2. CloudFront VPC Origin利用AZ ID、APIオリジンTLS、Authorization転送、HTTPメソッド。
3. CIDR/SG/ルートテーブルの確定値、RDS DB Subnet Groupとアクセス管理。
4. Cognitoコールバック、トークン保管、初回ユーザー作成とJWKS接続。
5. 通知対象日、Scheduler実行頻度/時刻、SNS重複・障害復旧。
6. API/DB/NATのインスタンス種別、稼働時間、費用上限、Secrets方式、バックアップ/復元。

これらの担当WBSは[判断ログ](decision-log.md)に記載。本書を「構築済みの確定設計」として扱わず、PoC結果で更新する。

## 8. 参考

- [GitHub README](../../README.md) / [GitHub WBS](../WBS.md) / [AWS Issue #27〜#34](https://github.com/omoy16/bakuraku-kintai/issues/27)
- [AWS CloudFront VPC Origins](https://docs.aws.amazon.com/ja_jp/AmazonCloudFront/latest/DeveloperGuide/private-content-vpc-origins.html)
- [AWS CloudFront OAC](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/private-content-restricting-access-to-s3.html)
- [AWS NAT Instance](https://docs.aws.amazon.com/vpc/latest/userguide/work-with-nat-instances.html)
- [AWS SSM/VPC Endpoint](https://docs.aws.amazon.com/systems-manager/latest/userguide/session-manager-getting-started-privatelink.html)
- [AWS RDS停止](https://docs.aws.amazon.com/ja_jp/AmazonRDS/latest/UserGuide/USER_StopInstance.html)
- [AWS Pricing Calculator](https://calculator.aws/)
