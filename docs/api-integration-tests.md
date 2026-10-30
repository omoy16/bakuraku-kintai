# WBS 1.8 — API単体・結合テスト

対象は[Issue #15](https://github.com/omoy16/bakuraku-kintai/issues/15)。
WBS 1.5・1.6・1.7を含むmain `765e78f51c8a548f4f67bc454bc01a1d7149a21a`を基準に、
既存130ケースを確認し、APIをまたぐ業務の流れと不足する障害・境界ケースを補った。
アプリケーションのAPI・DB定義・業務ルールの変更はない。

## 完了条件と試験の対応

| 完了条件 | 確認する内容 | 主な試験ファイル（backend/tests/） |
| --- | --- | --- |
| 夜勤 | JST・UTCの日跨ぎ、16時間以上でも同じ勤務が継続、未退勤確認から翌朝の退勤時刻へ修正 | `test_attendance.py`、`test_attendance_workflows.py` |
| 二重打刻 | 勤務中の再出勤・退勤後の再退勤を409、同時打刻は1件のみ成功、DBの勤務重複拒否 | `test_attendance.py`、`test_postgres.py` |
| 取消期限 | 出勤・退勤の両方でDB記録時刻から0秒・60秒は成功、60秒＋1μs・時計逆行は409 | `test_attendance_cancellation.py` |
| 履歴修正 | 理由・変更前後・操作者・操作日時、本人分離、古い操作IDの409、修正後の再打刻・取消と履歴のつながり | `test_attendance_correction.py`、`test_attendance_workflows.py` |
| エラー | 404/409/422/500/503、全DB利用エンドポイントの障害応答、ログ保存・commit失敗時の全rollback | `test_api_configuration.py`、`test_api_structure.py`、出退勤・取消・修正の各試験 |
| 証跡 | 実DBを含むpytestの結果・既存ブラウザ結合試験の結果をCIに保存、PRに実行結果とリンクを記録 | `.github/workflows/backend-tests.yml`、対応PR |

## 今回補ったケース

### 複数APIを続けて使う流れ

`test_attendance_workflows.py`はFastAPIのHTTP受付からサービス・実PostgreSQLまでを通す。
監査ログのつながりは、前操作の`after_values`と次操作の`before_values`が一致することでも検証する。

- 夜22時の出勤 → 翌日の16時間到達 → 二重出勤409 → 「退勤打刻を忘れた」 → 翌朝7時への修正 → 次の勤務開始 → その出勤を取消。新しいクライアントでも修正済み勤務と取消済み勤務が保持される。
- 退勤済み勤務を修正で勤務中へ戻す → 再退勤 → 退勤取消 → 理由つき再修正。古い画面の操作IDは409、`is_modified`は維持され、失敗操作で余分なログを残さない。
- 「まだ勤務中」で抑制した勤務の出勤時刻を前後に修正。旧確認を解除し、修正日時から16時間の判定を計算し直す。
- 別クライアントから未退勤確認と修正を同時実行。修正が先なら確認409、確認が先なら両方200を許容する。最終状態に古い確認の抑制が復活しないことを確認する。

### 取消と障害応答

- 既存の出勤取消の期限試験を退勤取消にも適用する。取消時計は`db_now`だけを固定し、保存済み監査時刻を起点に検証する。アプリの打刻時計とは区別する。
- 取消ログのINSERT後、PostgreSQLの遅延制約トリガーでcommit時に失敗させる。勤怠・監査ログがともに元の状態へ戻り、原因除去後は同じ取消を再試行できることを出勤・退勤の両方で確認する。
- DB障害は12通りのHTTPエンドポイント/メソッドで確認する。デモ利用者検索をテスト用に差し替えて各サービスのDB処理まで到達させ、503の本文が`{"detail":"Database unavailable"}`で統一されることと、livenessが200を保つことを確認する。

## 実行方法

通常のAPI試験にPlaywrightは不要。PostgreSQL 16は[READMEのセットアップ](../README.md)に従って起動する。
PowerShellの例はリポジトリルート・仮想環境有効化後に実行する。

```powershell
python -m pip install -r backend/requirements-dev.txt
# bakuraku_testが未作成の場合のみ実行
docker compose exec postgres createdb -U bakuraku bakuraku_test
$env:BAKURAKU_TEST_DATABASE_URL = "postgresql+psycopg://bakuraku:your-local-password@127.0.0.1:5432/bakuraku_test"
python dev.py test

# 機械可読な結果を保存する場合
python -m pytest -q --junitxml=pytest-results.xml

# 今回の業務フローだけを実行する場合
python -m pytest backend/tests/test_attendance_workflows.py -v
```

接続先にはテスト専用DBを指定する。試験はランダム名の専用スキーマへAlembicを適用し、
利用者と勤怠データを各試験で初期化する。終了時に削除するのは生成した試験スキーマだけ。
`BAKURAKU_DATABASE_URL`からテストDBを推測しない。

`BAKURAKU_TEST_DATABASE_URL`がなければ実DB試験はskipされる。
**skipがある実行だけでは、WBS 1.8の実DB検証完了とは扱わない。**
指定したテストDBに接続できない場合は失敗となる。

## CIと結果の確認

GitHub Actionsの`Backend tests`は2ジョブを実行する。

| ジョブ | 経路・対象 | 結果ファイルとArtifact名 |
| --- | --- | --- |
| `pytest` | Python 3.11 → FastAPI → PostgreSQL 16。純粋な入力検証、モデル、マイグレーションも含む | `pytest-results.xml` / `api-pytest-results` |
| `poc-e2e` | Chromium → Vite → FastAPI → PostgreSQL 16。既存画面11ケースの回帰確認 | `e2e-results.xml` / `poc-e2e-results` |

Actions画面で両ジョブの成功とpytestのskipなしを確認する。
Artifact内のJUnit XMLにはテスト名、件数、失敗・skipの情報があり、失敗時もアップロードを試みる。
PR本文に対象コミット、CI実行URL、成功・skip件数を記載する。

## 検証範囲

時計はテスト用の`get_clock`差し替えや取消用DB時計の固定で進め、16時間・60秒の実時間待機をしない。
SQL制約、行ロック、トランザクション、commit時の失敗は実PostgreSQLを使う。
この段階の本人分離は依存性の差し替えによる確認で、Cognito/JWTはWBS 3.xで扱う。
取消・修正・未退勤確認の新しいUIはWBS 2.x、AWS実環境と実端末は後続WBSの対象。
Starlette TestClientの既存httpx非推奨警告は本作業の対象外。
