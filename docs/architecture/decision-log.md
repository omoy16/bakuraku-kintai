# 設計判断・変更履歴・未決定事項

最終整理: 2026-11-13。**合意/コードで裏づけられたものを優先**し、過去の下書きを現行の確定値と混同しない。

## 設計の変遷（会話 + Issues + リポジトリ）

| 時期 | 当時の検討・決定 | 現在の扱い | 根拠 |
| --- | --- | --- | --- |
| 2026-10-15頃 | 勤怠WebアプリでRDS/EC2/Lambda/S3、VPC/NATなどAWSを学習 | **維持**。名称は「もう帰りたい。」から「爆楽勤怠」へ | [README](../../README.md) |
| 2026-10-20 | 旧基盤設計v0.1。東京、CloudFront+S3、Private EC2、Private RDS、VPC Lambda、NAT EC2。単一ユーザー、Flask、`notification_log`を想定 | **ネットワークの骨格のみ継承**。機能・DB・ランタイムは後続設計を優先 | 過去の基盤設計書v0.1（旧名称、2026-10-20） |
| 2026-10-21 | Cognitoによる複数デモユーザー、自己登録OFF、PKCE、本人の勤怠だけ操作 | **維持**。旧単一ユーザー前提を更新 | [WBS 3.x](https://github.com/omoy16/bakuraku-kintai/issues/23)、過去のアプリ設計書v0.2 |
| 2026-10-22〜24 | GitHub IssuesをWBS進捗の正本、PRで検証・マージ。45タスク/137hの初期計画 | **維持**。Day表記は着手日からの相対稼働日 | [WBS](../WBS.md) |
| 2026-10-25〜27 | 勤怠レコード単位、日跨ぎ・再出勤、取消は履歴保持。DBは`users`/`attendance_records`/`attendance_audit_logs`の3テーブル。通知専用テーブル廃止 | **確定・実装済み**。旧`notification_log`は不採用 | [Issue #8](https://github.com/omoy16/bakuraku-kintai/issues/8)、[models.py](../../backend/app/models.py) |
| 2026-10-27〜30 | Flask案からFastAPIへ移行。SQLAlchemy/Alembic、Router/Depends、PostgreSQL実DB、同時打刻409、監査ログ原子性、取消、16時間未退勤判定 | **main実装済み**。旧Flask+Gunicorn記述は歴史的案 | [#9](https://github.com/omoy16/bakuraku-kintai/issues/9)〜[#15](https://github.com/omoy16/bakuraku-kintai/issues/15) |
| 2026-10-31〜11-04 | Cognito User Pool。usernameは架空の社員番号（例`000001`）、自己登録不可。localはデモ用FastAPI認証コンテキスト。Web CryptoでPKCE、Amplify/`oidc-client-ts`を追加しない | **実装予定の決定方針**。Cognito・JWT検証は未実装 | [#23](https://github.com/omoy16/bakuraku-kintai/issues/23)、[#24](https://github.com/omoy16/bakuraku-kintai/issues/24)、[#25](https://github.com/omoy16/bakuraku-kintai/issues/25) |
| 2026-11-13 | README/Issuesと照合し基盤全体をレビュー。APIはPublic EC2ではなくPrivate EC2+VPC Originが現行案と確認 | **PoC前の方針**。実AZ、SG、HTTPS、管理経路を設計してから確定 | [README](../../README.md)、[#33](https://github.com/omoy16/bakuraku-kintai/issues/33) |

## 決定台帳

| ID | 分野 | 決定内容 | 状態 |
| --- | --- | --- | --- |
| D-01 | 学習目的 | 実データなし。AWSネットワーク、通信経路、セキュリティ、費用、障害復旧を学ぶ | 方針 |
| D-02 | フロント | HTML/CSS/Vanilla JS + Vite、非公開S3+CloudFront OAC。React/Amplify導入なし | 方針（アプリ基礎は実装済み） |
| D-03 | API | FastAPI、Private EC2、Uvicorn/systemd。VPC OriginのPoCが成功したら採用 | 方針/要検証 |
| D-04 | DB | PostgreSQL、Private RDS、Single-AZ、SQLAlchemy/Alembic。3テーブル。JST表示・UTC基準 | DBコード実装済み/RDS未構築 |
| D-05 | 認証 | Cognito + Authorization Code/PKCE。社員番号username、自己登録OFF。APIでaccess JWT検証、`sub`でDBユーザー識別 | 方針/未実装 |
| D-06 | NAT | Public NAT EC2にEIP、source/destination check OFF、ip_forward、iptables SNAT。NAT GW常設はしない | 方針/未実装 |
| D-07 | 定期処理 | EventBridge Scheduler→VPC Lambda→祝日API・RDS→SNS。通知は同一勤怠IDにつき一度を目標 | 方針/未実装 |
| D-08 | 可用性 | 検証環境では単一EC2、単一NAT EC2、RDS Single-AZ。ALBやMulti-AZは構築範囲外 | 方針 |
| D-09 | 管理 | SSHをインターネット公開しない。IAM/SSM/SGとCloudWatch/Budgetsを使う | 方針/未実装 |
| D-10 | 監査 | 勤怠更新と監査ログを同じトランザクション。通知専用テーブルなし、`reminder_sent_at`で送信成功を記録 | DB側実装済み/通知は未実装 |

## 旧案からの重要な修正

- **単一ユーザー → 複数の架空社員**: Cognitoの複数アカウントに対応し、本人の情報だけ処理する。アプリ内管理者機能は設けない。
- **Flask/Gunicorn → FastAPI/Uvicorn**: 旧PDFのアプリサーバー記述は採用しない。
- **旧`attendance`+通知ログ → 3テーブル**: 旧案の`work_date`列/「1日1件」方式を撤回。勤務レコードID単位で管理し、日跨ぎ・同日再出勤を許可。監査ログ追加。
- **公開EC2案 → Private EC2方針**: APIへの入口はCloudFront VPC OriginをPoC。結果次第で代替入口を再検討する。
- **通知の厳密1回保証は未達**: `reminder_sent_at`だけではSNS受付直後の停止・並列実行・不明結果を完全に防げない。SNS Standardメール自体も厳密な一回配信保証ではない。WBS 5.3で設計。
- **旧資料の09:00 JST・t4g.micro・db.t4g.micro・CIDRは暫定値**: コンソールで採用した実設定がない以上、確定値として扱わない。

## オープン事項（実装・構築前に決定）

| ID | 優先 | 課題 | 影響/決め方 | 対応先 |
| --- | --- | --- | --- | --- |
| O-01 | 高 | Private EC2の初期外向き通信・SSM管理経路がNAT構築より先に必要 | WBS 5.4を前倒し、またはSSM等のVPC Endpointを使う設計。費用も比較 | [#29](https://github.com/omoy16/bakuraku-kintai/issues/29)、[#38](https://github.com/omoy16/bakuraku-kintai/issues/38) |
| O-02 | 高 | VPC OriginのEC2条件、東京のAZ ID、経路・SG、APIメソッド・Authorization、キャッシュ | WBS 4.7のPoCで合否判定 | [#33](https://github.com/omoy16/bakuraku-kintai/issues/33) |
| O-03 | 高 | CloudFront→オリジンのHTTP/HTTPS、証明書、TLS方式 | 学習PoCと最終的なTLS保護を分けて決定。HTTPなら暗号化範囲を明記 | [#33](https://github.com/omoy16/bakuraku-kintai/issues/33)、[#42](https://github.com/omoy16/bakuraku-kintai/issues/42) |
| O-04 | 高 | Cognitoユーザー初回アクセス時のDB自動生成、デモユーザー扱い、トークン保管/期限切れ、JWKS取得経路 | #23–26で仕様・境界条件を検証 | [#26](https://github.com/omoy16/bakuraku-kintai/issues/26) |
| O-05 | 高 | Lambda通知対象日、祝日API障害、夜勤判定、同時送信・送信結果不明 | 先にテストデータと期待値を決定。通知過多を防ぐ | [#35](https://github.com/omoy16/bakuraku-kintai/issues/35)〜[#37](https://github.com/omoy16/bakuraku-kintai/issues/37) |
| O-06 | 高 | 実CIDR/AZ ID、SG・NACL、DB Subnet Group、RDS接続情報の保管方法 | AWS利用開始前に設定表確定。Secrets Manager/SSM Parameter Storeの必要性と料金も比較 | [#28](https://github.com/omoy16/bakuraku-kintai/issues/28)〜[#30](https://github.com/omoy16/bakuraku-kintai/issues/30) |
| O-07 | 中 | CloudWatch監視、ログ保持、予算上限、日次停止/再起動、バックアップ復元 | 実機課金と停止・復旧試験を実施 | [#27](https://github.com/omoy16/bakuraku-kintai/issues/27)、[#43](https://github.com/omoy16/bakuraku-kintai/issues/43) |
| O-08 | 中 | API更新時のデプロイ手順（パッケージ供給、systemd、ロールバック） | Private EC2への転送・再起動手順を確定 | [#31](https://github.com/omoy16/bakuraku-kintai/issues/31) |

## 根拠と読み替え方

- 実装済みかどうかは[mainのソース](../../backend/app/)と[Alembic](../../backend/migrations/versions/)およびGitHub Issuesを優先。
- 2026-10-20旧基盤設計書v0.1・2026-10-21旧アプリ設計書v0.2は過去の会話で作成した原案。**リポジトリに存在しない添付資料なので、このPRにそのまま添付/転載はしていない**。引用した項目は後続のIssues/READMEとの整合性を確認し、古いものは「旧案」と明記した。
- [AWS VPC Origins公式](https://docs.aws.amazon.com/ja_jp/AmazonCloudFront/latest/DeveloperGuide/private-content-vpc-origins.html)（東京`apne1-az3`除外）
- [AWS Session ManagerのVPC Endpoint](https://docs.aws.amazon.com/systems-manager/latest/userguide/session-manager-getting-started-privatelink.html)
- [AWS RDS停止/再起動](https://docs.aws.amazon.com/ja_jp/AmazonRDS/latest/UserGuide/USER_StopInstance.html)
