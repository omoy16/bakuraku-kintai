# 爆楽勤怠 | AWS構築・検証・証跡計画

**版: 2026-11-13 / WBS 3.x〜6.x向け**  
この文書は**試験計画**であり、「成功した」実測結果ではない。ローカル/CIの既存試験と、未実施のAWS実機試験を分ける。

## 1. 進捗の大枠

| WBS | 主題 | GitHubでの現在地 | 確認先 |
| --- | --- | --- | --- |
| 0.x | MVP・開発基盤 | ローカルPoC実装、ソースあり | [README](../../README.md) |
| 1.1〜1.8 | DB/API・取消・16h・修正・監査・テスト | 対応Issueはclose、mainに実装 | [#8](https://github.com/omoy16/bakuraku-kintai/issues/8)〜[#15](https://github.com/omoy16/bakuraku-kintai/issues/15) |
| 2.x | UI・モーダル | 計画、AWS本番連携とは別 | [#16](https://github.com/omoy16/bakuraku-kintai/issues/16)〜[#22](https://github.com/omoy16/bakuraku-kintai/issues/22) |
| 3.x | Cognitoログイン・JWT・ユーザー分離 | 未完了/未検証 | [#23](https://github.com/omoy16/bakuraku-kintai/issues/23)〜[#26](https://github.com/omoy16/bakuraku-kintai/issues/26) |
| 4.x | VPC、SG/SSM、RDS、EC2、S3、CloudFront | 未完了/未構築 | [#27](https://github.com/omoy16/bakuraku-kintai/issues/27)〜[#34](https://github.com/omoy16/bakuraku-kintai/issues/34) |
| 5.x | 祝日API、Lambda、SNS、NAT EC2 | 未完了/未構築 | [#35](https://github.com/omoy16/bakuraku-kintai/issues/35)〜[#40](https://github.com/omoy16/bakuraku-kintai/issues/40) |
| 6.x | E2E、セキュリティ、コスト、受入 | 未完了 | [#41](https://github.com/omoy16/bakuraku-kintai/issues/41)〜[#45](https://github.com/omoy16/bakuraku-kintai/issues/45) |

GitHub Issuesは進捗の正本。過去に記録されたローカルCI成功件数は**当時のコミットの証跡**であり、今日のAWS環境を保証しない。

## 2. 変更前→変更→変更後の証跡ルール

ネットワーク、OS、認証、DB、停止試験では必ず以下の順序を守る。

1. **変更対象・目的・予想される影響**: どの通信/状態が変わるか、変わらないことを期待するかを記述。
2. **変更前の証跡**: 同じコマンド/GUI項目/ログを保存し、時刻（JST/UTC）と操作対象を記録。実IP・アカウントID・秘密情報は公開Issueに記載しない。
3. **変更**: 操作・設定の差分、必要な権限、復旧手順（ロールバック）を記録。
4. **変更後の証跡**: 変更前と**同一観測項目**を取得。期待値と実値を比較。
5. **復旧試験**: 元の設定やサービス状態に戻し、再度同じコマンド/疎通で回復を確認。
6. **成果物**: Issueに概要と合否・原因を残し、詳細な構築メモ/スクリーンショットは秘密情報を除去して保管。

### 証跡記録テンプレート

\`\`\`markdown
### 試験ID: T-xx / 実施日時（JST）
- 対象/目的:
- 変更内容・影響範囲:
- 変更前観測（コマンド・画面・時刻）:
- 事前の期待値:
- 実施操作:
- 変更後観測（同一項目）:
- 実際の結果・期待値との差異:
- 復旧操作と復旧後観測:
- 合否/残課題/関連Issue:
\`\`\`

## 3. AWS構築・確認順とゲート

### Stage A | AWSアカウント・コスト・VPC

- WBS 4.1: 東京リージョン・Budgets・プロジェクトタグ・停止/削除基準を決める。作成前に予算通知状態を記録。
- WBS 4.2: VPC、IGW、Public1/Private2（異AZ）、CIDR、Subnet Association、Route Table。例示CIDRを実値として採用するか確認。
- WBS 4.3: App/RDS/Lambda/NATのSG、最小IAM、EC2用インスタンスプロファイル、SSMの管理経路。
- **依存関係ゲート**: Private EC2を作る前にSSMとソフトウェア導入用の外向き経路を確保。現WBSはNAT 5.4を後ろに置いているため、NAT前倒し案か必要なVPCE案をIssueで合意する。

### Stage B | DB・アプリ・公開入口

- WBS 4.4: RDS Single-AZ、DB Subnet Group、Publicly accessible=false、接続SG、SSL、管理/アプリDB権限、Alembic。
- WBS 4.5: Private EC2上でUvicorn/systemd、/api/health、RDS接続、SSM。SSH公開を使わず起動・再起動・ログ確認が可能。
- WBS 4.6: Private S3+OAC+CloudFront。S3直アクセス拒否、HTTPS、静的ファイル配信。
- WBS 4.7: VPC Originで/api/*をEC2へルーティング。オリジンのAZ ID、SG、HTTP(S)、Authorization、HTTPメソッド、キャッシュを検証。
- WBS 4.8: Cognitoの別デモユーザーでログインし、APIで本人の打刻/履歴と他人アクセス拒否を検証。

### Stage C | 定期処理とNAT

- WBS 5.1/5.2: 祝日APIの応答、土日・祝日、連休明け、夜勤、年跨ぎ、未退勤の抽出。
- WBS 5.3: SNS Email購読、1勤怠IDあたりの送信成功管理、失敗・並列・結果不明の処理。
- WBS 5.4: NAT EC2のSource/Dest Check、ip_forward、FORWARD、POSTROUTING SNAT、永続化。
- WBS 5.5: VPC LambdaがRDS localと祝日API/SNSへの外向き経路を正しく使う。
- WBS 5.6: NAT停止前→停止→再起動後、iptablesルール有効→削除→復旧時の同一観測比較。

### Stage D | 受入・セキュリティ・コスト

- WBS 6.1: ログイン→出退勤→夜勤→取消/修正→通知までの業務E2E。
- WBS 6.2: JWT署名/iss/exp/client_id/token_use、他人データ、S3/RDS/EC2非公開、IAM・Secrets。
- WBS 6.3: NAT GW対NAT EC2料金比較（同条件）、実課金、EC2/RDS停止と自動再開リスク、Scheduler停止。
- WBS 6.4/6.5: 設計書・実機構成図・残課題・運用手順とデモを提出。

## 4. 詳細試験マトリクス（計画）

| ID | 試験 | 変更/観測する項目 | 合格条件 | WBS |
| --- | --- | --- | --- | --- |
| T-01 | CloudFront→S3 | Behavior、OAC、S3 Block Public Access、HTTP結果 | HTML/JSをHTTPSで取得でき、S3直接GET不可 | 4.6 |
| T-02 | CloudFront→Private EC2 | Origin/AZ ID/SG/API Behavior/Headers | /api/healthに到達し、AppにPublic IP不要 | 4.7 |
| T-03 | API認証 | Bearer JWT、署名・期限・client_id・sub | 正常tokenのみ成功、無効/別社員は拒否 | 3.3/3.4 |
| T-04 | App EC2→RDS | RDS公開設定、SG、5432接続、SSL | Private内通信だけ成功、外部から接続不可 | 4.4/4.5 |
| T-05 | Lambda→RDS | Lambda ENI/SG、DB接続 | Private内で成功、NAT不要 | 5.5 |
| T-06 | Lambda→祝日API | Route Table、NAT iptables、レスポンス | NAT稼働時に取得、停止時に失敗 | 5.1/5.5 |
| T-07 | NAT停止/復旧 | EC2状態、route、ip_forward、iptables、外部HTTP(S) | 停止時外部失敗、RDS経路は生存、復旧後回復 | 5.6 |
| T-08 | SNAT破壊/復元 | POSTROUTING/FORWARDカウンタ | 削除で外向き失敗、復元で成功 | 5.6 |
| T-09 | SSM管理 | Agent到達性、IAM、ポート22、SSM Endpoint/NAT | SSH非公開でも接続でき、管理経路を復旧できる | 4.3 |
| T-10 | 祝日・夜勤判定 | 対象日、外部API不達、JSON不正 | 誤通知しない。境界日の期待値が一致 | 5.1/5.2 |
| T-11 | SNS重複 | 二回実行、並列、Publish不明、DB更新失敗 | 設計された扱い通り。厳密1回の虚偽保証なし | 5.3 |
| T-12 | 打刻・修正 | ロック、排他制約、監査ログ、UTC/JST | 夜勤・二重打刻・取消・修正が整合 | 6.1 |
| T-13 | 監視 | EC2/DB/ Lambdaの異常、CloudWatch、Budgets | 期待したアラーム/ログが確認できる | 6.2/6.3 |
| T-14 | 停止と費用 | EC2/RDS/Schedulerと残存リソース | 停止・再起動/削除後の費用と動作を説明できる | 6.3 |

## 5. 参考の確認コマンド（実値はマスク）

> 実行前にAWS CLIのプロファイルとリージョン、対象権限を確認する。以下は読み取り用。操作系コマンドは構築当日に復旧手順とセットで作る。

\`\`\`bash
# AWS上の観測: アカウント情報は公開Issueに貼らない
aws configure list
aws ec2 describe-vpcs --region ap-northeast-1
aws ec2 describe-availability-zones --region ap-northeast-1 \
  --query 'AvailabilityZones[].{Name:ZoneName,Id:ZoneId,State:State}'
aws ec2 describe-subnets --region ap-northeast-1 \
  --query 'Subnets[].{SubnetId:SubnetId,Cidr:CidrBlock,Az:AvailabilityZone,AzId:AvailabilityZoneId}'
aws ec2 describe-route-tables --region ap-northeast-1
aws ec2 describe-security-groups --region ap-northeast-1
aws ec2 describe-vpc-endpoints --region ap-northeast-1
aws rds describe-db-instances --region ap-northeast-1

# NAT EC2 内の観測（変更前/停止後/復旧後）
ip -4 addr
ip -4 route
sysctl net.ipv4.ip_forward
sudo iptables -L FORWARD -n -v
sudo iptables -t nat -L POSTROUTING -n -v

# 到達性確認は対象環境の許可/トークン不要な宛先で
curl -I --max-time 10 https://example.org
\`\`\`

### 変更前後で特に比較するもの

| 変更操作 | 変化があり得る観測 | **変わってはいけない観測** |
| --- | --- | --- |
| AppのSG制限 | APIの成功/失敗、TCP80/443の接続元 | RDSの非公開設定、想定外ポート開放なし |
| Privateのdefault route追加 | 外部HTTPSの成否 | VPC localのRDS:5432接続 |
| NAT EC2停止 | 外部HTTPS、SSM/JWKS到達性（NAT依存なら） | 同一VPC内のRDS接続 |
| ip_forward OFF | NAT転送の成否 | EC2のローカル操作・RDSデータ |
| Cognito User Pool設定 | PKCEログイン/JWT/ユーザー分離 | 未認証の勤怠書込みが不可 |
| Scheduler無効化 | Lambda定期呼び出し件数 | 既存勤怠データの整合性 |
| RDS停止 | DB health/打刻API応答 | 静的Web配信、データの物理保持 |

## 6. 安全・費用チェック（作業終了時）

- AWS BudgetsとCost Explorerの通知/実請求を確認する。
- 動いているEC2、RDS、Lambda、Schedulerなどを一覧で確認し、意図した停止状態にする。
- RDSを停止しても**ストレージ/バックアップ料金が残る**こと、7日後に自動再起動することを確認する。
- EIP/IPv4、EBS、S3、CloudFront、CloudWatch Logs、スナップショット、VPC Endpoint等の残存を確認する。
- 実行ログ、コンソール画面、CLI出力にはアカウント識別子、秘密情報、実メール、JWT/アクセスキーなどを含めない。
- 検証したWBSのIssueへ結果を記録し、未完了ならCloseしない。

## 7. 実際の結果の書き込み先

この表の「合格条件」は**期待値**であり、まだ検証結果ではない。実測値・スクリーンショットは個別Issue/PRへ記録し、完了後に基本設計とネットワーク図を実環境の値へ更新する。

- [WBS進捗表](../WBS.md)
- [AWS基盤Issue](https://github.com/omoy16/bakuraku-kintai/issues/27)
- [NAT/通知Issue](https://github.com/omoy16/bakuraku-kintai/issues/35)
- [セキュリティ試験](https://github.com/omoy16/bakuraku-kintai/issues/42)
- [費用・停止運用](https://github.com/omoy16/bakuraku-kintai/issues/43)
