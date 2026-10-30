# WBS 1.5 打刻取消API

対応Issue: [#12](https://github.com/omoy16/bakuraku-kintai/issues/12)

## API契約

- `POST /api/attendance/cancel`、リクエスト本文・ID指定なし。
- 認証導入前はWBS 1.4と同じ明示seed済みデモユーザー。将来はDependsの認証主体へ差し替える。
- 対象は**その利用者の最新の操作ログが `clock_in` または `clock_out` の場合のみ**。過去の任意の打刻を取消さない。
- 成功 200: `{"record_id":123,"cancelled_operation":"clock_in","status":"not_working"}`
  （退勤取消は `cancelled_operation: "clock_out"`, `status: "working"`）。
- 取消対象なし／二重取消／対象の状態変更／期限切れは409。DB障害は503。
- 期限切れのdetailは `Cancellation window expired`。機密性のあるDB情報は返さない。

## 60秒判定と整合性

1. 利用者行を`SELECT FOR UPDATE`でロック（WBS 1.4とのロック順序を統一）。
2. 利用者に紐づく最新監査ログ（`attendance_audit_logs.id`降順）を読み、操作種別を検査。
3. 対象勤怠行を`SELECT FOR UPDATE`でロック。
4. **PostgreSQLの `clock_timestamp()`** を取得し、最新監査ログの`operated_at`との差を計算。
5. `0 <= 差 <= 60秒`のときのみ実行。ちょうど60秒は許可、60秒超や時計逆行は409。
6. 勤怠行の更新と取消の監査ログ追記を同一DBトランザクションでcommit。監査ログ保存・commit失敗時は双方rollback。

この期限の起点は**打刻日時`clock_in_at`/`clock_out_at`ではなく、DBが操作ログを記録した`operated_at`**。
クライアントが送る時刻に依存しない。利用者行ロックによって、同一利用者の他の出退勤／取消と直列化する。

- **出勤取消**：レコードを削除せず`cancelled_at`にDB時刻を保存し、`cancel_clock_in`監査ログを追加。勤務状態・簡易履歴には表示しない。
- **退勤取消**：`clock_out_at = NULL`に戻し、元の出勤レコードを勤務中として復元。`cancel_clock_out`監査ログを追加。
- 両方とも`updated_at`を更新し、変更前後の`clock_in_at`/`clock_out_at`/`cancelled_at`を監査ログへ保存。
- 取消ログそのものは再取消できない。連続undoや任意レコードの取消は今回対象外。
- **フロントエンドの取消ボタンはWBS 2.6**。WBS 1.5ではAPIとDBの境界まで実装。

新規テーブル・マイグレーションは不要。WBS 1.2で設計した`cancelled_at`と監査ログ操作種別を利用する。

## ローカル確認

PostgreSQL起動・`python dev.py init-db`・`python dev.py seed-demo`後、
`python dev.py api`を実行。PowerShellの別ウィンドウで：

```powershell
$base = "http://127.0.0.1:8000"
Invoke-RestMethod -Method Post "$base/api/attendance/clock-in"
Invoke-RestMethod -Method Post "$base/api/attendance/cancel"
Invoke-RestMethod "$base/api/attendance/status"
Invoke-RestMethod "$base/api/attendance/history"

# 退勤取消の確認：別の出勤・退勤を順に行う
Invoke-RestMethod -Method Post "$base/api/attendance/clock-in"
Invoke-RestMethod -Method Post "$base/api/attendance/clock-out"
Invoke-RestMethod -Method Post "$base/api/attendance/cancel"
Invoke-RestMethod "$base/api/attendance/status"
```

期待値：出勤取消後は`not_working`で簡易履歴にそのレコードがなく、
退勤取消後は`working`で退勤時刻がnull。APIの同じ取消を二度押すと409。

`python dev.py test`は`BAKURAKU_TEST_DATABASE_URL`を設定したPostgreSQL 16で実DB試験を実行。
`backend/tests/test_attendance_cancellation.py`は60秒境界、本人分離、二重取消、同時取消、監査ログ失敗時のrollbackを検証する。
