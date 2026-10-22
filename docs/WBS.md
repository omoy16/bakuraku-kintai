# 爆楽勤怠 WBS（GitHub Issues対応表）

> WBS v1.0 / 45タスク / 計画工数 **137時間** / 18稼働日＋予備2日。
> この表は当初計画の索引です。**進捗・優先順位・担当変更は各GitHub Issueを正本として管理**してください。開始日はまだ決めていません。Dayは実際の着手日からの相対稼働日です。

## フェーズ概要

フェーズ | WBS | Issues | 工数 | 予定Day
--- | --- | --- | ---: | ---
2日MVP | 0.x | #1–#7 | 16h | 1–2
API・DB | 1.x | #8–#15 | 25h | 3–6
UI仕上げ | 2.x | #16–#22 | 19h | 6–8
Cognito認証 | 3.x | #23–#26 | 14h | 8–10
AWS基盤 | 4.x | #27–#34 | 26h | 10–13
通知・NAT | 5.x | #35–#40 | 22h | 13–16
総合試験 | 6.x | #41–#45 | 15h | 16–18

## タスク一覧

| WBS ID | タスク（Issue） | 工数 | 予定Day | 依存WBS ID |
| --- | --- | ---: | --- | --- |
| 0.1 | [#1 要件の凍結](https://github.com/omoy16/bakuraku-kintai/issues/1) | 1h | 1 | — |
| 0.2 | [#2 GitHub／プロジェクト雛形](https://github.com/omoy16/bakuraku-kintai/issues/2) | 2h | 1 | 0.1 |
| 0.3 | [#3 ローカル開発環境](https://github.com/omoy16/bakuraku-kintai/issues/3) | 2h | 1 | 0.2 |
| 0.4 | [#4 FastAPI打刻PoC](https://github.com/omoy16/bakuraku-kintai/issues/4) | 3h | 1 | 0.3 |
| 0.5 | [#5 簡易ホームUI](https://github.com/omoy16/bakuraku-kintai/issues/5) | 3h | 2 | 0.4 |
| 0.6 | [#6 簡易履歴一覧](https://github.com/omoy16/bakuraku-kintai/issues/6) | 2h | 2 | 0.4 |
| 0.7 | [#7 PoC結合試験](https://github.com/omoy16/bakuraku-kintai/issues/7) | 3h | 2 | 0.5 / 0.6 |
| 1.1 | [#8 RDS向けDB物理設計](https://github.com/omoy16/bakuraku-kintai/issues/8) | 3h | 3 | 0.7 |
| 1.2 | [#9 SQLAlchemy・Alembic](https://github.com/omoy16/bakuraku-kintai/issues/9) | 3h | 3 | 1.1 |
| 1.3 | [#10 API構造化](https://github.com/omoy16/bakuraku-kintai/issues/10) | 2h | 3 | 0.7 |
| 1.4 | [#11 打刻API確定版](https://github.com/omoy16/bakuraku-kintai/issues/11) | 3h | 4 | 1.2 / 1.3 |
| 1.5 | [#12 打刻取消API](https://github.com/omoy16/bakuraku-kintai/issues/12) | 3h | 4 | 1.4 |
| 1.6 | [#13 長時間未退勤判定](https://github.com/omoy16/bakuraku-kintai/issues/13) | 3h | 4–5 | 1.4 |
| 1.7 | [#14 履歴・修正・監査ログ](https://github.com/omoy16/bakuraku-kintai/issues/14) | 4h | 5 | 1.2 / 1.4 |
| 1.8 | [#15 API単体／結合テスト](https://github.com/omoy16/bakuraku-kintai/issues/15) | 4h | 5–6 | 1.5 / 1.6 / 1.7 |
| 2.1 | [#16 C案デザイン反映](https://github.com/omoy16/bakuraku-kintai/issues/16) | 3h | 6 | 0.7 |
| 2.2 | [#17 ワンボタンの状態制御](https://github.com/omoy16/bakuraku-kintai/issues/17) | 2h | 6 | 1.6 / 2.1 |
| 2.3 | [#18 未退勤確認モーダル](https://github.com/omoy16/bakuraku-kintai/issues/18) | 3h | 6–7 | 1.6 / 2.2 |
| 2.4 | [#19 履歴と『変更あり』表示](https://github.com/omoy16/bakuraku-kintai/issues/19) | 3h | 7 | 1.7 / 2.1 |
| 2.5 | [#20 打刻修正モーダル](https://github.com/omoy16/bakuraku-kintai/issues/20) | 3h | 7 | 1.7 / 2.4 |
| 2.6 | [#21 取消と通信エラーUI](https://github.com/omoy16/bakuraku-kintai/issues/21) | 2h | 7–8 | 1.5 / 2.2 |
| 2.7 | [#22 UI最終確認](https://github.com/omoy16/bakuraku-kintai/issues/22) | 3h | 8 | 2.3 / 2.5 / 2.6 |
| 3.1 | [#23 Cognito User Pool構築](https://github.com/omoy16/bakuraku-kintai/issues/23) | 3h | 8 | 2.7 |
| 3.2 | [#24 ログイン／ログアウト](https://github.com/omoy16/bakuraku-kintai/issues/24) | 4h | 8–9 | 3.1 |
| 3.3 | [#25 FastAPI JWT検証](https://github.com/omoy16/bakuraku-kintai/issues/25) | 4h | 9 | 3.1 / 1.3 |
| 3.4 | [#26 ユーザー分離検証](https://github.com/omoy16/bakuraku-kintai/issues/26) | 3h | 9–10 | 3.2 / 3.3 |
| 4.1 | [#27 コスト警報とタグ](https://github.com/omoy16/bakuraku-kintai/issues/27) | 2h | 10 | 0.7 |
| 4.2 | [#28 VPC・サブネット](https://github.com/omoy16/bakuraku-kintai/issues/28) | 3h | 10 | 4.1 |
| 4.3 | [#29 SG・IAM・SSM設定](https://github.com/omoy16/bakuraku-kintai/issues/29) | 4h | 10–11 | 4.2 |
| 4.4 | [#30 RDS PostgreSQL作成](https://github.com/omoy16/bakuraku-kintai/issues/30) | 3h | 11 | 4.3 / 1.2 |
| 4.5 | [#31 Private EC2にAPI配置](https://github.com/omoy16/bakuraku-kintai/issues/31) | 4h | 11–12 | 4.3 / 4.4 |
| 4.6 | [#32 S3＋CloudFront配信](https://github.com/omoy16/bakuraku-kintai/issues/32) | 3h | 12 | 4.2 / 2.7 |
| 4.7 | [#33 CloudFront VPC Origin PoC](https://github.com/omoy16/bakuraku-kintai/issues/33) | 4h | 12–13 | 4.5 / 4.6 |
| 4.8 | [#34 AWS全体の打刻E2E](https://github.com/omoy16/bakuraku-kintai/issues/34) | 3h | 13 | 3.4 / 4.7 |
| 5.1 | [#35 祝日APIクライアント](https://github.com/omoy16/bakuraku-kintai/issues/35) | 3h | 13 | 4.8 |
| 5.2 | [#36 勤務日・未退勤判定](https://github.com/omoy16/bakuraku-kintai/issues/36) | 4h | 13–14 | 5.1 / 1.6 |
| 5.3 | [#37 SNS通知・重複防止](https://github.com/omoy16/bakuraku-kintai/issues/37) | 3h | 14 | 5.2 |
| 5.4 | [#38 NAT EC2の構築](https://github.com/omoy16/bakuraku-kintai/issues/38) | 5h | 14–15 | 4.2 / 4.3 |
| 5.5 | [#39 Lambda VPC＋Scheduler](https://github.com/omoy16/bakuraku-kintai/issues/39) | 4h | 15 | 5.3 / 5.4 |
| 5.6 | [#40 NAT疎通・障害試験](https://github.com/omoy16/bakuraku-kintai/issues/40) | 3h | 15–16 | 5.5 |
| 6.1 | [#41 業務シナリオ試験](https://github.com/omoy16/bakuraku-kintai/issues/41) | 4h | 16 | 5.6 |
| 6.2 | [#42 セキュリティ試験](https://github.com/omoy16/bakuraku-kintai/issues/42) | 3h | 16–17 | 6.1 |
| 6.3 | [#43 費用・停止運用検証](https://github.com/omoy16/bakuraku-kintai/issues/43) | 3h | 17 | 6.1 |
| 6.4 | [#44 構成図・運用手順・発表](https://github.com/omoy16/bakuraku-kintai/issues/44) | 3h | 17 | 6.2 / 6.3 |
| 6.5 | [#45 最終デモ・受入確認](https://github.com/omoy16/bakuraku-kintai/issues/45) | 2h | 17–18 | 6.4 |

## マイルストーンの完了条件

1. **M1 / Day2 ローカル最小デモ**：出勤 → 退勤 → 履歴表示を確認
2. **M2 / Day6 API・DB確定**：PostgreSQL移行・取消・修正・16時間判定・主要pytest通過
3. **M3 / Day8 C案UI**：PC/スマホ・1ボタン・確認モーダル・「変更あり」詳細
4. **M4 / Day10 Cognito認証**：ログイン/ログアウト/失効・JWT検証・ユーザー分離
5. **M5 / Day13 AWS打刻**：Cognito → CloudFront → EC2 → RDS の実機確認
6. **M6 / Day16 通知/NAT**：Lambda・外部祝日API・SNS・NAT EC2の動作確認
7. **M7 / Day18 受入完了**：業務・セキュリティ・費用検証と最終デモ

## 開発運用ルール（暫定）

- **開始時**：担当するIssueに着手宣言。依存Issueの未完了を確認
- **実装時**：`feature/<簡潔な機能名>` などの作業ブランチを作成
- **レビュー**：PR本文に対応Issue・確認方法・未解決事項を書く
- **完了時**：完了条件を確認し、検証の証跡を残してからIssueを閉じる
- **機密保持**：認証情報・AWS接続情報・実際の勤怠データはGitHubに公開しない

計画や実装順の変更は、WBSのIDを再利用して追跡できるよう、Issue上で記録します。