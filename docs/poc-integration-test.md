# WBS 0.7 PoC結合試験

対応Issue: [#7](https://github.com/omoy16/bakuraku-kintai/issues/7)

## 結果

2026年10月24日（JST）、WBS 0.6までを取り込んだコミット
`630d98001bcea579f38e14cc8bf7dec8004e3630` に対して実施。
**ブラウザ結合試験11件、既存pytest31件が成功し、Viteの本番ビルドも成功した。**
アプリケーションコードの変更が必要な不具合は見つからなかった。

実ブラウザ → Viteの `/api` プロキシ → FastAPI → SQLiteの経路で、
Issue #7の「ローカルで出勤→退勤→履歴確認が通る」を確認した。
再実行用の試験は `tests/e2e/test_poc.py` に保存している。

## 実行環境

| 項目 | 使用バージョン・設定 |
| --- | --- |
| OS | Linux / Debian系 |
| Python / pytest | 3.12.14 / 9.1.1 |
| FastAPI / Uvicorn | 0.162.0 / 0.54.0 |
| Node.js / npm / Vite | 24.19.0 / 11.9.0 / 7.3.7 |
| Playwright / Chromium | 1.64.1 / 154.0.8037.57 |
| 画面サイズ | PC 1280×900、スマホ幅 390×844 |
| ブラウザのタイムゾーン | America/Los_Angeles（画面はJSTになることを検証） |
| データ | 各試験の一時SQLite、固定の架空ユーザー `demo-user` |

## 結合試験の証跡

| ケース（pytest名） | 操作・確認した結果 | 結果 |
| --- | --- | --- |
| `test_clock_in_out_history_and_reload[desktop]` | 空履歴→出勤→勤務中の履歴→再読み込み→退勤→同じIDの退勤済み履歴→再読み込みで保持→次の出勤が先頭に表示 | PASS |
| `test_clock_in_out_history_and_reload[mobile]` | 同じ操作を390px幅で実施。横スクロールが発生しないことも確認 | PASS |
| `test_api_restart_preserves_active_shift` | 出勤後にAPIプロセスを停止・再起動。同一ID・出勤時刻の勤務中レコードを保持し、退勤可能 | PASS |
| `test_history_failure_allows_punch_and_recovers` | 履歴応答だけ503に差し替え。履歴エラーを表示しながら出勤可能。解除して再確認すると勤務中の履歴が復旧 | PASS |
| `test_status_failure_disables_punch_and_recovers` | 状態応答だけ503に差し替え。打刻不可・エラー表示。解除して再確認すると復旧 | PASS |
| `test_api_outage_and_recovery` | 実際にAPIプロセスを停止。再確認で状態・履歴エラーと打刻不可。API再起動・再確認で復旧 | PASS |
| `test_stale_state_conflict_refreshes_without_duplicate` | 別リクエストで先に出勤し、古い画面から出勤。実APIの409後に最新状態を再取得し、重複レコードなし | PASS |
| `test_lost_post_response_is_not_retried` | 実APIで出勤を保存後、ブラウザへの応答を切断。POSTは1回だけで、GETから勤務中・履歴を復元 | PASS |
| `test_rapid_clicks_send_one_post` | 続けて2回クリック。POSTは1回、保存レコードも1件 | PASS |
| `test_overnight_shift_and_jst_display[jst-midnight]` | 過去のUTC 14:30出勤を投入。日跨ぎ・16時間超でも勤務中。JSTの同日23:30を表示し、手動退勤可能 | PASS |
| `test_overnight_shift_and_jst_display[utc-midnight]` | 過去のUTC 23:30出勤を投入。日跨ぎ・16時間超でも勤務中。JSTの翌日08:30を表示し、手動退勤可能 | PASS |

全ケースで未処理のJavaScript例外がないことも確認する。
異常応答の差し替えはPlaywrightの通信制御を使用し、通常の打刻・履歴や409の経路は実APIを使用する。
日跨ぎ試験は過去の固定データで再現し、実時間で一晩待つ試験ではない。

実行結果:

```text
python dev.py test
31 passed, 1 warning in 0.48s

BAKURAKU_CHROMIUM_PATH=/usr/bin/chromium \
BAKURAKU_E2E_ARTIFACT_DIR=/tmp/bakuraku-poc-evidence \
python -m pytest tests/e2e -v --junitxml=/tmp/bakuraku-poc-evidence/results.xml
11 passed in 19.93s

python dev.py build
vite v7.3.7 / 4 modules transformed / built in 101ms
```

既存pytestの警告はStarlette TestClientによるHTTPX利用の非推奨警告。
今回の実行では失敗は発生していない。
JUnit XMLと各ケース終了時のスクリーンショットは指定の証跡ディレクトリへ生成した。
スクリーンショットはPC・スマホ幅とも目視確認した。証跡ファイルは実行ごとに再生成する。

## 再実行手順

リポジトリのルートで、READMEに従って仮想環境を有効化する。
開発用のAPI・Viteを停止し、**127.0.0.1の8000番・5173番ポートを空ける**。
並列実行には対応していない。

```bash
python -m pip install -r backend/requirements-e2e.txt
npm --prefix frontend ci
python -m playwright install chromium
python -m pytest tests/e2e -v
```

Linuxでブラウザのシステム依存が不足する場合は、Playwrightの案内に従って導入する。
既にChromiumがある環境では、ブラウザのダウンロードの代わりに
`BAKURAKU_CHROMIUM_PATH` に実行ファイルの絶対パスを指定できる。

| 環境変数 | 内容 |
| --- | --- |
| `BAKURAKU_CHROMIUM_PATH` | 任意。既存Chromiumの実行ファイル。未指定ならPlaywright同梱ブラウザ |
| `BAKURAKU_E2E_ARTIFACT_DIR` | 任意。各ケース終了時のスクリーンショットの保存先 |

試験はAPI・Viteを自動起動し、終了時に停止する。
`BAKURAKU_DB_PATH` は各ケースの一時ディレクトリへ上書きするため、
開発DBの初期化や削除は不要。起動済みの開発サーバーは再利用しない。
`python dev.py test` はこれまでどおりバックエンド31件のみを実行し、
Playwrightのインストールは必要ない。

## 確認範囲

今回の結果はローカルPoCとChromiumでの検証結果。
スマホ幅はブラウザのビューポートによる確認で、実機のiOS / Android試験は含まない。
10秒タイムアウトの実時間経過は今回の専用ケースに含めず、通信断は応答切断とAPI停止で確認した。
Cognito、ユーザー分離、PostgreSQL、AWS配信、取消・修正は後続WBSの対象とする。
