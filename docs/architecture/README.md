# 爆楽勤怠 | AWS基盤設計ドキュメント

> 版: 2026-11-13 レビュー用ドラフト / 対象: 学習用AWS環境（東京リージョン）  
> **現時点の設計を記録した文書であり、AWS構築済み・料金確定・疎通確認済みを意味しません。**

## どこから読むか

| 読む順番 | 文書 | 想定読者・用途 |
| --- | --- | --- |
| 1 | [5分で読める概要](overview-5min.md) | 全体像、設計意図、現在地を素早く理解 |
| 2 | [AWS基盤基本設計](aws-basic-design.md) | 要件、サービス責務、認証、データ、運用、コスト |
| 3 | [VPC・通信経路詳細設計（ドラフト）](aws-network-design.md) | サブネット、ルート、Security Group、NAT、SSM |
| 4 | [設計判断・変更履歴](decision-log.md) | 過去の会話から何を決め、何を変更したか |
| 5 | [構築・検証・証跡計画](validation-plan.md) | WBS、確認観点、変更前後の比較、障害・停止試験 |
| 図 | [編集可能なAWS構成図](aws-architecture.drawio) | diagrams.net（draw.io）で編集。AWS4アイコンを使用 |

## この文書の位置づけ

- 正本の優先順位: **実際の main コードとマイグレーション / 完了済みIssueで検証された実装** → **現行READMEと未完了Issueの設計方針** → **本ドキュメントの整理案** → **旧ドラフト**。
- GitHub Issuesは**作業進捗の正本**。このフォルダは設計内容・理由・根拠の読み物として使う。
- 記号は **[実装済]、[方針]、[仮置き]、[要検証]、[未決定]** を区別する。
- 完了済みAPI・DBの実装確認と、未実施AWS実機構築を混同しない。
- 旧称「もう帰りたい。」で作成された2026-10-20の基盤設計v0.1および10-21のアプリ設計v0.2は**歴史的資料**。旧設計にあったFlask、単一利用者、\`notification_log\`、日次1件制約、旧APIパスなどは現在の確定仕様ではない。
- 「コンソールで選んだ実値」をまだ取得できていないCIDR・AZ・インスタンスサイズ・証明書・予算上限などは勝手に確定しない。

## 主な参照先

- [リポジトリREADME](../../README.md) ／ [WBS](../WBS.md) ／ [全Issue](https://github.com/omoy16/bakuraku-kintai/issues)
- [DB論理・物理設計 #8](https://github.com/omoy16/bakuraku-kintai/issues/8)
- [Cognito #23–26](https://github.com/omoy16/bakuraku-kintai/issues/23)
- [AWS基盤 #27–34](https://github.com/omoy16/bakuraku-kintai/issues/27)
- [通知・NAT #35–40](https://github.com/omoy16/bakuraku-kintai/issues/35)
- [構成・検証・費用 #41–45](https://github.com/omoy16/bakuraku-kintai/issues/41)

## 更新方法

設計変更時は、(1) 対応Issueと判断根拠、(2) [decision-log.md](decision-log.md)の変更記録、(3) 影響する設計書・構成図、(4) 検証証跡、を同じPRで更新する。未確定を断定に変える場合は実機確認または合意が必要。
