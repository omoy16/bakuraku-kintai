# 爆楽勤怠 | VPC・通信経路 詳細設計（ドラフト）

**基準: 2026-11-13 / WBS 4.2〜4.7・5.4〜5.6向け**

この文書のネットワーク値には、2026-10-20の旧基盤設計v0.1から引き継いだ**例示値**が含まれる。AWS実機で採用した値ではないため、構築時に変更・確定し、その変更をPRとIssueに記録する。

## 1. ネットワーク配置

| 項目 | 例示値 / 方針 | 用途 | 状態 |
| --- | --- | --- | --- |
| Region | ap-northeast-1（東京） | 学習環境 | [方針] |
| VPC CIDR | 10.0.0.0/16 | VPCのIPv4空間 | [仮置き] |
| Public A | 10.0.1.0/24 | NAT EC2、IGW向け経路 | [仮置き] |
| Private A | 10.0.11.0/24 | FastAPI EC2、Lambda ENI、RDS候補 | [仮置き] |
| Private B | 10.0.12.0/24 | RDS DB Subnet Groupの別AZ候補 | [仮置き] |
| Availability Zone | Private AとBは異なるAZ | RDS DB Subnet Group | [要確定] |
| AZ ID条件 | **apne1-az3はCloudFront VPC Origin対象外** | App EC2の配置先選定 | [要検証] |
| IGW | VPCに1つアタッチ | NAT EC2のInternet向け | [方針] |
| NAT EC2 | Public A、EIPあり | Private Aからの外向き通信 | [方針] |
| RDS | Publicly accessible=false、Single-AZ | PostgreSQL | [方針] |
| App EC2 | Private A、Public IPなし | FastAPI | [方針] |

注意:
- AZ名の末尾（例: ap-northeast-1a）はアカウントにより実AZの対応が異なる。**AZ IDを取得して制限に抵触しないことを確認**する。
- Private BがRDSのDB Subnet Groupのみに使用されても、**サービス自体がMulti-AZになるわけではない**。
- EC2/DBサイズは未確定。旧設計のt4g.micro、db.t4g.microなどは試算用の仮置き。
- SGはステートフル。NACLは初期はデフォルトを想定し、戻りの一時ポートを誤って塞がない。

### 1.1 障害・セキュリティ境界を含む概念図

\`\`\`mermaid
flowchart TB
  CF["CloudFront（VPC OriginをPoC）"]
  S3["非公開S3/OAC"]
  COG["Cognito（ブラウザから直接認証）"]
  SUBGRAPH["（以下はネットワーク内部）"]
  subgraph VPC["VPC 10.0.0.0/16 [例示]"]
    subgraph PUB["Public A 10.0.1.0/24 [例]"]
      NAT["NAT EC2 / EIP / iptables"]
    end
    subgraph PRA["Private A 10.0.11.0/24 [例]"]
      APP["EC2 FastAPI"]
      L["VPC Lambda ENI"]
      DB1["RDS Single-AZ（配置先候補）"]
    end
    subgraph PRB["Private B 10.0.12.0/24 [例]"]
      DB2["RDS DB Subnet Group（別AZ候補）"]
    end
  end
  WEB["ブラウザ"] --> CF
  WEB -. "PKCE" .-> COG
  CF --> S3
  CF -->|"API経路"| APP
  APP -->|"5432 local"| DB1
  L -->|"5432 local"| DB1
  APP -. "外向き443（必要時）" .-> NAT
  L -->|"祝日API等のHTTPS"| NAT
  NAT --> IGW["IGW → Internet"]
\`\`\`

**図のRDS二か所は二つのDBインスタンスを表さない。** 単一のRDSインスタンスと、その配置候補を含む2AZサブネットグループを示す概念図である。

## 2. ルートテーブル（IPv4・例）

| Route Table | 宛先CIDR | Target | 対象 | 意図 |
| --- | --- | --- | --- | --- |
| rt-public | 10.0.0.0/16 | local | Public A | VPC内 |
| rt-public | 0.0.0.0/0 | Internet Gateway | Public A | NAT EC2の外向き |
| rt-private-a | 10.0.0.0/16 | local | Private A | App/Lambda→RDSはここ |
| rt-private-a | 0.0.0.0/0 | NAT EC2のENIまたはインスタンス | Private A | 公開祝日API、SNS公開Endpoint、必要に応じSSM/JWKS |
| rt-private-b | 10.0.0.0/16 | local | Private B | 原則DB用、外向き0.0.0.0/0不要 |

- **localルートとNATを区別する**: RDSのPrivate IPへ接続する場合、Default routeのNATには送られない。
- Public AにIGWルートを付けても、Private AのEC2がそのままInternetへ出られるわけではない。
- VPC Originを使う場合、VPCにIGWのアタッチが必要というAWS公式条件がある。**CloudFront→Private EC2がIGWを通るという意味ではない**。
- IPv6は初期構築対象外。必要な時に別設計とする。

## 3. Security Groupの通信許可案

許可する「理由」と実際の送信元を分ける。ポートは初期PoC案であり、HTTPS化等で変わったら設定表も更新する。

| SG | Inbound（案） | Outbound（案） | 根拠/注意 |
| --- | --- | --- | --- |
| sg-app | **CloudFront VPC Originが用いる適切なSG/送信元**→TCP80（仮） | sg-rds→TCP5432、必要な公開HTTPS→TCP443 | APIを全世界から直接開けない。Origin通信方式はPoCで確定 |
| sg-rds | sg-app、sg-lambda→TCP5432 | 原則インスタンス側に新規の外向きは不要（運用要件で再評価） | DBをInternetへ公開しない |
| sg-lambda | インバウンド新規接続なし | sg-rds→TCP5432、外向き443 | Lambda VPC ENIがアクセスする先 |
| sg-nat | Private A（例10.0.11.0/24）→TCP80/443等の必要な転送 | Internet→TCP80/443等（必要最小限） | TCP forwardingルール/iptablesとの両方が必要 |
| sg-ssm-endpoint（採用時） | sg-app等→TCP443 | 応答はステートフル | VPCEを使う場合にのみ |

補足:
- 「CloudFrontの世界中の配信IPを適当にSGへ全登録する」「App EC2のポートを0.0.0.0/0に公開する」は行わない。
- APIオリジンのポート80案は**CloudFront→EC2間の暗号化保証がないPoC**。最終的なTLSはIssue #33/#42で決める。
- NAT転送時の送信元/戻りパケット、SGとiptablesの実効動作をパケット観測で確認。NACLをカスタマイズする場合は一時ポートを含めて再設計。
- RDS SGはDBエンジンのポート5432を限定。外部端末からDBへの直アクセスは許可しない。
- CloudFront OACはS3用の設定。**VPC Originへのアクセス制御と同一ではない**。

## 4. 通信フローごとの経路

| No | 通信 | 起点 → 宛先 | Internet / NAT | 期待値 |
| --- | --- | --- | --- | --- |
| F-01 | 画面配信 | Browser→CloudFront→S3(OAC) | ブラウザ側Internet、VPC NATは不要 | HTTPSで画面取得、S3直アクセス不可 |
| F-02 | ログイン | Browser→Cognito Managed Login→Callback | ブラウザ側Internet、VPC NATは不要 | Authorization Code + PKCE |
| F-03 | API | Browser→CloudFront /api/*→Private EC2 | VPC Origin。EC2のPublic IP不要 | FastAPI到達/認証トークン転送 |
| F-04 | DB | App EC2→RDS:5432 | VPC local。**NAT不要** | 取得/更新成功 |
| F-05 | DB（定期） | Lambda ENI→RDS:5432 | VPC local。**NAT不要** | 未退勤候補取得 |
| F-06 | 祝日API | Lambda ENI→NAT EC2→IGW→外部HTTPS | **NAT経由** | 正常時200/JSON。NAT停止で失敗 |
| F-07 | SNS | Lambda ENI→NAT EC2→IGW→SNS公開Endpoint | **NAT経由を検証** | Publishの成否/ログ。Endpoint採用時は再設計 |
| F-08 | EC2管理 | EC2 SSM Agent→SSMサービス（Session Manager） | NATかSSM用VPCEが必要 | 22/TCP開放なしで管理可能 |
| F-09 | JWT鍵 | Private EC2→Cognito JWKS公開Endpoint | NAT等の外向き経路 | 公開鍵取得・更新が可能 |
| F-10 | パッチ/導入 | EC2→パッケージ配布/ソース | NAT、ミラー、VPC Endpoint等を選定 | 起動からデプロイまで再現可能 |

## 5. NAT EC2詳細（学習用）

### 5.1 事前条件

1. EC2はPublic Aに配置し、外向きIGWルートとEIPを確認。
2. EC2の**Source/Destination Checkを無効**にする。
3. LinuxのIPv4転送を有効にし、OS再起動後にも永続化する。
4. SG、NACL、iptablesのINPUT/FORWARD/POSTROUTINGを役割ごとに区別。
5. Private AのデフォルトルートをNAT EC2（実設定で受け入れ可能なターゲット）へ設定。
6. NATを停止しても管理経路まで失わないよう、停止/起動の操作手段を別途確認。

### 5.2 参考コマンド（**AWS環境ではそのまま無批判に実行しない**）

\`\`\`bash
# 変更前の証跡をまず取得
ip -4 addr
ip -4 route
sysctl net.ipv4.ip_forward
sudo iptables -L FORWARD -n -v
sudo iptables -t nat -L POSTROUTING -n -v

# 変更例（実際の出口インターフェース名を確認してから）
sudo sysctl -w net.ipv4.ip_forward=1
sudo iptables -t nat -A POSTROUTING -s 10.0.11.0/24 -o ens5 -j MASQUERADE

# 同一観測を変更後に取得
sysctl net.ipv4.ip_forward
sudo iptables -L FORWARD -n -v
sudo iptables -t nat -L POSTROUTING -n -v
\`\`\`

この例だけでは**FORWARDチェーンの必要な許可が未完成**。既定ポリシー、ESTABLISHED/RELATEDの戻り許可、SNAT元ネットワーク、ルール重複防止、永続化、OS再起動後の検証が必要。インターフェース名ens5は例示。Amazon Linux 2023でのiptables管理方式も実機で確認する。

### 5.3 NAT停止・復旧試験

- 変更前: Private EC2/Lambdaの外部HTTPS成功、RDS:5432成功、Route Table、NATのiptablesカウンタ、SG、EC2状態を保存。
- NAT停止: 外部HTTPSが失敗することを観測。ただし**RDSのVPC内接続は継続すること**も同時に確認する。SSMの接続切断リスクを先に評価。
- NAT再起動: ip_forward、iptables永続化、NAT宛デフォルトルート、EIP、外部HTTPSが回復することを確認。
- ルール削除試験: 事前・事後の同一カウンタ/外部疎通結果を比較し、元に戻せるコマンドを用意する。
- **NAT停止は本番運用向けの障害注入ではなく、架空データでの学習実験**。実行前に費用・時間・管理経路を確認。

## 6. EC2管理接続（設計上の重要課題）

WBS 4.5のPrivate EC2配置が、WBS 5.4のNAT構築より先にある。

**問題**: App EC2にPublic IPを持たせずSSHも公開しないため、EC2側のSSM AgentがAWS Systems ManagerへアクセスできないとSession Managerが利用できない。同様にパッケージ取得やCognito JWKS取得も外向き到達性が必要。

| 案 | 内容 | 注意 |
| --- | --- | --- |
| A（学習目的に合致） | NAT EC2構築・疎通検証をPrivate App EC2の初期管理より前倒し | NATが単一障害点。構築順のIssue修正が必要 |
| B | SSM/ssmmessages等のInterface VPC Endpointを先に用意 | Endpoint時間課金とSG、追加エンドポイント依存に注意。一般インターネット全ての代替にはならない |

現時点の本書は**案AもBも決定していない**。WBS 4.3と5.4でどちらを採るか決める。AWS公式はSSMエージェントのバージョンに応じた必要なサービスEndpointを指定している。公開鍵・OS更新まで含めた通信経路は個別に整理する。

## 7. 設定値を確定するための実機確認

次の情報は架空の例をそのままGitHubへ「確定値」として転載しない。AWS作成時に確認し、アカウントID/IP・秘密情報など公開不要の値はマスキングする。

| 確認項目 | 例の確認方法 | 証跡に残すもの |
| --- | --- | --- |
| AZ ID | EC2コンソールのAZ / CLI describe-availability-zones | 名前とIDの対応、非対応AZ回避 |
| VPC/Subnet CIDR | VPCコンソール / describe-subnets | CIDR、Route Table関連付け |
| ルート | VPC Route Table / describe-route-tables | 全サブネットのlocal/default route |
| SG | Security Groups / describe-security-groups | 送信元SG/CIDR、方向、ポート |
| NAT | EC2のS/D check、EIP、ip_forward、iptables | 変更前/後、再起動前/後の実効値 |
| SSM | Systems Manager Fleet Manager/Session Manager | 22非公開、Agent登録状態、セッション成功 |
| RDS | RDS DB/DB Subnet Group/接続 | Publicアクセス=false、SG、DB疎通 |
| CloudFront | Distribution/Origin/Behavior | VPC Origin状態、HTTP(S)、API method/header/cache |
| 外向き | HTTPS接続結果、Lambdaログ、NATカウンタ | 正常・停止・復旧の比較 |

## 8. 公式参考

- [CloudFront VPC Originの要件・東京対応AZ](https://docs.aws.amazon.com/ja_jp/AmazonCloudFront/latest/DeveloperGuide/private-content-vpc-origins.html)
- [NATインスタンス](https://docs.aws.amazon.com/vpc/latest/userguide/work-with-nat-instances.html)
- [SSM PrivateLink](https://docs.aws.amazon.com/systems-manager/latest/userguide/session-manager-getting-started-privatelink.html)
- [Session Managerトラブルシューティング](https://docs.aws.amazon.com/systems-manager/latest/userguide/session-manager-troubleshooting.html)
- [RDS VPC/DB Subnet Group](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/USER_VPC.WorkingWithRDSInstanceinaVPC.html)
- [WBS 4.2 VPC](https://github.com/omoy16/bakuraku-kintai/issues/28)、[4.7 Origin PoC](https://github.com/omoy16/bakuraku-kintai/issues/33)、[5.4 NAT](https://github.com/omoy16/bakuraku-kintai/issues/38)
