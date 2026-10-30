# WBS 1.4 PostgreSQL打刻API

対応Issue: [#11](https://github.com/omoy16/bakuraku-kintai/issues/11)

## 変更範囲

WBS 1.2の3テーブルと、WBS 1.3のAPIRouter・Depends・共通例外処理を使い、
APIの出退勤・勤務状態・簡易履歴・DB接続確認をPostgreSQLへ切り替えた。
DDL・マイグレーションの追加はない。取消・修正APIとJWT認証は後続WBSで実装する。

URL、HTTPメソッド、勤怠JSONの項目名、200/201/409/503の使い分けを引き継ぐ。
`user_id`は固定文字列`demo-user`から、DBが生成した`users.id`のJSON整数へ変更する。
値を1と仮定しない。フロントエンドの履歴検証も正の数値IDに対応した。
`GET /api/health/db`は`{"status":"ok","database":"postgresql"}`を返す。

## 起動とデモ利用者

初回セットアップは[README](../README.md)を参照。

1. PostgreSQL 16を用意し、`BAKURAKU_DATABASE_URL`を明示設定する。
2. `python dev.py init-db`で既存のAlembicマイグレーションを適用する。
3. `python dev.py seed-demo`で`local:demo-user`に対応する利用者を明示登録する。
4. `python dev.py api`と`python dev.py frontend`を起動する。

init-dbとseed-demoは再実行可能。API起動・マイグレーションで利用者を自動登録しない。
APIはDependsで`local:demo-user`を検索し、登録済みの生成IDを使う。
未設定URL・不正URL・未マイグレーション・未seed・接続障害時にSQLiteへ切り替えない。
認証導入前のローカル用デモAPIで、クライアントから利用者IDや打刻時刻を受け取らない。
JWT認証実装時には、固定デモ取得を検証済みの認証主体の取得へ置き換える。

## 接続の寿命

FastAPIのlifespanでアプリ単位のEngineを作成し、終了時にdisposeする。
Engine作成時にはDBへ接続せず、実際の接続はリクエストで必要になった時点で行う。
URLが未設定・不正でも`GET /api/health`は利用可能で、DB依存APIは503になる。
接続・プール待ちには5秒の上限を設け、接続セッションはUTC・READ COMMITTEDとする。

DBヘルスチェックはSELECT 1による接続確認で、利用者取得には依存しない。
マイグレーションやデモ登録の完了までは保証しないため、接続確認が200でも未seedなら勤怠APIは503になる。

## 出退勤のトランザクション

1. 生成された利用者IDの`users`行をSELECT FOR UPDATEでロックする。
2. 未取消・未退勤の勤怠を取得する。退勤時など、対象勤怠にも行ロックを取る。
3. 現在の状態を検証する。出勤済みなら二重出勤を、未出勤なら退勤を409で拒否する。
4. ロック取得・状態確認後に、Dependsで渡された時計関数からサーバー時刻を取得する。
5. 勤怠の追加・更新と、操作ログの追記を同じSession・トランザクションで行う。
6. コミットに成功して接続が解放されてから、APIの成功応答へ戻る。

勤務中の行がまだ存在しない初回出勤も直列化できるよう、安定して存在する利用者行を先にロックする。
ロック順序は利用者→勤怠。後続の取消・修正処理も同じ順序へそろえる。
異なる利用者の勤怠操作をアプリ側の全体ロックでは止めない。

同時出勤・同時退勤は一方が成功し、もう一方が状態を再確認して409になる。
DBの部分一意索引とGiST排他制約も、二重出勤と勤務時間の重複を防ぐ。
状態の事前SELECTだけで整合性を保証しない。

## 操作ログ

出勤時は`clock_in`、退勤時は`clock_out`を追記する。
出勤の`before_values`はSQL NULL、それ以外のスナップショットは次のキーを使う。

```json
{"clock_in_at":"2026-10-29T00:00:00+00:00","clock_out_at":null,"cancelled_at":null}
```

日時はUTCのISO 8601、未設定値はJSON null。actor_user_idは勤怠所有者と同じ生成ユーザーID。
操作日時はDB側のclock_timestamp()で保存し、退勤時のupdated_atも明示更新する。
操作ログの保存に失敗した場合、勤怠更新もロールバックする。
取消・修正のログや入力理由の仕様は、それぞれの後続WBSで扱う。

## エラーの対応

| 状況・制約 | HTTP / detail |
| --- | --- |
| 二重出勤・uq_attendance_active_user | 409 / Already working |
| 勤務中の記録がない退勤 | 409 / Not working |
| 出勤より前の退勤・ck_attendance_time_order | 409 / Clock is earlier than clock-in time |
| ex_attendance_overlap | 409 / Attendance period overlaps existing record |
| 接続・DB処理・コミット・プール待ち失敗 | 503 / Database unavailable |

DB制約による409への変換はSQLSTATEと制約名の組み合わせで限定する。
監査ログの制約違反などを二重出勤へ誤変換しない。例外はロールバック後に変換する。
プログラム中の予期しないValueErrorなどはDB障害として捕捉せず500になり、書込みはロールバックする。
DB接続先・SQL・元の例外はAPI応答に含めない。

## 日跨ぎ・過去データ

勤務中の検索は日付で絞らず、日跨ぎ・16時間超でも勤務中を維持する。
出退勤が同時刻の場合や、退勤直後の同日再出勤を許可する。
取消済みのレコードは勤務状態と簡易履歴から除外する。

既存SQLiteファイルは保持する。自動変換・コピー・削除はしない。
`BAKURAKU_DB_PATH`と`app.database`は旧PoCの保存用ヘルパーにのみ残り、現在のAPIには使わない。
旧SQLiteデータを引き継ぐ必要がある場合は、別途移行方針を決める。

## 検証

`BAKURAKU_TEST_DATABASE_URL`を設定したPostgreSQL 16で、API試験と既存のモデル・マイグレーション試験を実行する。
各試験はランダム名の専用スキーマを使い、既存スキーマ・SQLiteファイルを変更しない。
ブラウザ試験も専用PostgreSQLスキーマを作成し、init-db・seed-demo・API起動を実行する。

```bash
python dev.py test
python -m pytest tests/e2e -q
```

検証対象は、通常の出退勤と監査ログ、日跨ぎ・長時間勤務、同時出退勤、所有者分離、取消済み除外、
時刻逆行、時間重複409、監査ログ挿入失敗の原子性、コミット時まで遅延したDBエラーの503と全更新のロールバック、
ロック取得後の時計読み取り、生成IDが1以外の場合、明示seed、CLI再実行、API設定不備時のliveness。
最終コミットのCI結果と件数・証跡は対応PRに記録する。

## 公式技術資料

- [PostgreSQL 16：行ロック](https://www.postgresql.org/docs/16/explicit-locking.html#LOCKING-ROWS)
- [SQLAlchemy 2.0：Sessionとトランザクション](https://docs.sqlalchemy.org/en/20/orm/session_basics.html)
