# WBS 1.7 — 履歴・修正・監査ログ

Issue: [#14](https://github.com/omoy16/bakuraku-kintai/issues/14)

## 修正できる内容

本人の勤怠IDを指定して出勤・退勤日時を修正する。管理者・承認フローは設けない。
既存の`attendance_audit_logs.change_reason`を利用するため、DDL変更や追加マイグレーションは不要。

| 項目 | 仕様 |
| --- | --- |
| 修正理由 | 必須。前後の空白を除いて1〜500文字。操作ログごとに保存 |
| 出勤・退勤日時 | 両フィールド必須。ISO 8601のタイムゾーンつき日時。UTCへ正規化 |
| 退勤日時NULL | 一般修正でも明示的な`null`を許可し、勤務中へ戻す |
| 時刻チェック | 退勤≧出勤。等しい時刻は空区間として許可。サーバー現在時刻より未来の日時は拒否 |
| 他の勤務との競合 | 既存の部分一意・GiST排他制約で二重勤務中・勤務時間重複を拒否。隣接する勤務は許可 |
| 取消済み | 本人の詳細・ログ参照は可能、修正は不可。通常一覧には含めない |
| 値が同じ修正 | 409。理由だけの追記は行わず、不要な修正ログを作らない |
| 通知成功済み | `reminder_sent_at`を維持。同じ勤怠IDへの再通知を発生させない |
| 未退勤確認済み | 日時修正で`overdue_confirmed_at` / `overdue_confirmed_choice`をクリアし、変更後の日時から要確認を再評価 |

日付を跨ぐ修正でも勤怠IDは変わらず、そのIDに操作履歴が残る。勤務日は既存設計どおり出勤日時のJST日付から求める。
明示的な修正の結果として退勤する場合のみ退勤日時を保存し、未退勤確認から自動で退勤させない。

## API

| メソッド | URL | 200の応答 |
| --- | --- | --- |
| GET | `/api/attendance/records` | 有効な本人勤怠の配列。出勤日時降順、同日時はID降順 |
| GET | `/api/attendance/records/{record_id}` | 本人の勤怠詳細。取消済みも対象 |
| PATCH | `/api/attendance/records/{record_id}` | 修正後の勤怠詳細 |
| GET | `/api/attendance/records/{record_id}/audit-logs` | 操作日時降順、同日時はID降順の監査ログ配列 |

勤怠詳細は従来の`id` / `user_id` / `clock_in_at` / `clock_out_at`に、`cancelled_at`、`is_modified`、`latest_operation_id`を追加した形式。
`is_modified`は、その勤怠に`update`操作ログが1件以上あればtrue。出退勤や60秒取消だけではtrueにしない。
既存`GET /history`・`/status`・出退勤APIの応答形式は維持する。

PATCHの本文例：

```json
{
  "clock_in_at": "2026-10-29T09:00:00+09:00",
  "clock_out_at": "2026-10-29T18:00:00+09:00",
  "expected_operation_id": 456,
  "change_reason": "退勤打刻を忘れたため"
}
```

`record_id`と`expected_operation_id`には取得結果の値を使い、固定IDを前提にしない。
修正APIは上記4フィールド以外を422で拒否する。所有者・操作者・操作日時・取消状態はクライアントから指定できない。
現段階の認証依存は既存の明示seedしたデモ利用者。Cognitoによる本人認証はWBS 3.xで実装する。すべての参照・更新に依存関数で確定した利用者IDを使う。

| HTTP | 内容 |
| --- | --- |
| 404 | 勤怠が存在しない、または他の利用者の勤怠。応答を共通化 |
| 409 | 古い操作ID、取消済み、日時変更なし、未来日時、二重勤務中、勤務時間の重複 |
| 422 | 本文不足、余分なフィールド、理由の不備、タイムゾーンなし、出退勤の前後関係不正、不正なID |
| 503 | DB未設定・接続・ログ保存・コミットなどのDB障害。内部SQLや接続情報は返さない |

監査ログは`id`、`attendance_record_id`、`actor_user_id`、`operation`、`before_values`、`after_values`、`change_reason`、`operated_at`を返す。
スナップショットは出勤・退勤・取消日時を含み、初回出勤の`before_values`だけnull。日時はUTC。ログの更新・削除APIは設けない。

## 古い画面からの上書きと同時操作

`latest_operation_id`は、その勤怠の最新監査ログID。取得した値をPATCHの`expected_operation_id`として送る。
既存の監査ログがない勤怠ではnullとなり、最初の修正ではnullを明示的に送る。
省略は許可しない。IDはJSON整数で、文字列・真偽値は拒否する。

1. 同じ利用者の行をロックし、その後に対象勤怠をロックする。出退勤・取消・未退勤確認とロック順を統一する。
2. 所有者・取消状態を確認し、取得時の操作IDとDBの最新操作IDを比較する。
3. 日時を検証し、修正と理由つき`update`ログを同一トランザクションで保存する。
4. commit成功後にだけ200を返す。保存やcommitに失敗すれば勤怠とログを両方ロールバックする。

日時が変更された後に元の値へ戻された場合も、操作IDが変わるため古い画面の更新は409になる。
勤怠の詳細・一覧を取得するSQLでは日時と操作IDを同じSELECTで読む。複数SELECT間で「古い日時＋新しい操作ID」が組み合わされることを避ける。
未退勤の確認は日時を変更しないため、操作IDは進めない。

修正後は最新操作が`update`になるので、既存の60秒取消APIは修正前の古い打刻を取り消さない。修正のやり直しは新しい修正理由でPATCHする。
409時は詳細・ログ・勤務状態を再取得し、利用者が修正内容を再確認する。応答不明時にもPATCHを自動再送・自動上書きしない。

## PowerShellでの確認

専用の開発DBでmigration・明示seedを実行し、`python dev.py api`で起動する。
実データを使わず、サンプルのIDと日時は自分で作成した勤怠に置き換える。

```powershell
$base = "http://127.0.0.1:8000/api/attendance"
Invoke-RestMethod "$base/records"
$recordId = 123 # 上の一覧にある本人の勤怠ID
$record = Invoke-RestMethod "$base/records/$recordId"
$body = @{
    clock_in_at = "2026-10-29T09:00:00+09:00"
    clock_out_at = "2026-10-29T18:00:00+09:00"
    expected_operation_id = $record.latest_operation_id
    change_reason = "退勤打刻を忘れたため"
} | ConvertTo-Json
$utf8Body = [System.Text.Encoding]::UTF8.GetBytes($body)
Invoke-RestMethod -Method Patch "$base/records/$recordId" `
    -ContentType "application/json; charset=utf-8" -Body $utf8Body
Invoke-RestMethod "$base/records/$recordId/audit-logs"
Invoke-RestMethod "$base/status"
```

同じ本文を再送すると古い操作IDで409になる。変更後の詳細を再取得して新しい操作IDを使う。
Windows PowerShellでも日本語の修正理由を保つため、本文はUTF-8バイト列で送る。

## 検証と後続WBS

```text
python -m pip install -r backend/requirements-dev.txt
# BAKURAKU_TEST_DATABASE_URL はテスト専用PostgreSQLに設定
python dev.py test
```

入力契約、本人分離、JST日跨ぎ、修正済み判定、NULLによる勤務再開、時間重複・隣接・空区間、古い操作ID、同時修正・出退勤・取消、
ログ保存失敗・コミット時の失敗によるロールバック、通知成功時刻の維持、API再作成後の永続性を検証する。
詳細取得中に別セッションで更新しても、日時と操作IDが同じ読取スナップショットで返ることを実DBで検証する。

ローカルにPostgreSQLがない場合、実DBテストはskipとなる。実DBと既存ブラウザの回帰試験はGitHub ActionsのPostgreSQL 16で実行する。
今回のUI追加はなく、履歴の「変更あり」表示はWBS 2.4、修正モーダルはWBS 2.5。手動実機確認とは分けて結果をPRへ記録する。

実装上の参照資料：
- [PostgreSQL 16: 行ロック](https://www.postgresql.org/docs/16/explicit-locking.html#LOCKING-ROWS)
- [Pydantic: 日時型の検証](https://docs.pydantic.dev/latest/api/standard_library_types/#datetimes)
