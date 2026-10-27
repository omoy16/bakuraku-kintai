# PostgreSQL・SQLAlchemy・Alembic（WBS 1.2 / #9）

## 対象と現在のAPI

[#8](https://github.com/omoy16/bakuraku-kintai/issues/8) のDB設計と2026-10-27の補足に沿って、PostgreSQL用のモデル・接続・初期マイグレーションを用意した。開発・CIの検証対象は **PostgreSQL 16**。

| ファイル | 役割 |
| --- | --- |
| `backend/app/models.py` | 3テーブルのSQLAlchemy 2.0モデル |
| `backend/app/postgres.py` | 接続URL、UTC接続、コミット／ロールバック |
| `backend/migrations/versions/0001_attendance_schema.py` | 独立した初期DDLと逆向きのDDL |
| `backend/app/seed_demo_user.py` | 明示実行するローカルデモユーザー登録 |
| `backend/tests/test_postgres.py` | PostgreSQL上のマイグレーション・制約・同時更新の検証 |

この段階の打刻API・`/api/health/db`・`python dev.py init-db` は引き続きSQLite PoCを使用する。`BAKURAKU_DATABASE_URL`を設定しただけではAPIの接続先は変わらない。API構造化は #10、PostgreSQLを使った打刻APIへの切替は #11 で行う。

## ローカルDBの起動とマイグレーション

既存のPython仮想環境を有効にし、リポジトリのルートで実行する。Docker Composeがある場合は同梱の `compose.yaml` を利用できる。手動でPostgreSQL 16を用意した場合は、起動を省略し接続URLをそのDBへ変更する。

PowerShellの例（下記のパスワードはローカル開発専用）：

```powershell
python -m pip install -r backend/requirements-dev.txt
$env:BAKURAKU_POSTGRES_PASSWORD = "local-dev-only"
$env:BAKURAKU_DATABASE_URL = "postgresql+psycopg://bakuraku:local-dev-only@127.0.0.1:5432/bakuraku"
docker compose up -d --wait postgres
python -m alembic -c backend/alembic.ini upgrade head
python -m alembic -c backend/alembic.ini current
python -m alembic -c backend/alembic.ini check
```

bash / WSLの環境変数設定は次のとおり。それ以外のコマンドは同じ。

```bash
export BAKURAKU_POSTGRES_PASSWORD='local-dev-only'
export BAKURAKU_DATABASE_URL='postgresql+psycopg://bakuraku:local-dev-only@127.0.0.1:5432/bakuraku'
```

`current` に `0001_attendance_schema (head)`、`check` に `No new upgrade operations detected.` が表示されれば基本構造は一致している。`check`だけではCHECK制約・排他制約のすべてを比較できないため、後述の実DBテストも実施する。

接続URLは環境変数からのみ読み込む。Python側では `.env` を自動読込しない。`postgresql://` は `postgresql+psycopg://` に正規化する。他のDBやドライバーは拒否し、URL未指定時は接続せずに失敗する。パスワードに `@` や `%` が含まれる場合はURLエンコードする。実環境の認証情報はコード・Issue・PRに書かない。

初期マイグレーションは `btree_gist` を `public` に作成する。導入済みの場合は再作成しない。対象DBで拡張を導入できるユーザーで実行する。RDS本体・接続経路・実際の権限確認は #30 で扱う。

DBはコンテナ停止後も名前付きボリュームに残る。停止・再起動は次のコマンドを使う。

```bash
docker compose stop postgres
docker compose start postgres
```

## 作成されるテーブルと制約

| テーブル | 保存する内容 | 主なDB制約・索引 |
| --- | --- | --- |
| `users` | Cognitoとの対応・表示名・登録日時 | `cognito_sub` 一意 |
| `attendance_records` | 出退勤ペア・出勤取消・通知成功日時・作成／更新日時 | 時刻順序、勤務中ユーザーの部分一意索引、期間のGiST排他制約、ユーザー別履歴索引 |
| `attendance_audit_logs` | 対象勤怠・操作者・操作種別・変更前後JSONB・`change_reason`・操作日時 | 操作種別のCHECK、勤怠別の履歴索引 |

- 主キーは `bigint GENERATED ALWAYS AS IDENTITY`。3本の外部キーは `ON DELETE RESTRICT`。
- 日時カラムは `timestamptz`。接続時はUTCに固定し、勤務日は出勤日時をJSTに変換して求める。
- 有効な勤務中レコードは1ユーザーにつき最大1件。
- 有効な勤務期間を `[出勤, 退勤)` として比較する。同日再出勤・日跨ぎ・隣接する勤務・出退勤同時刻を許可し、時間の重複を登録時も更新時も拒否する。未退勤の終了は無期限として扱う。
- `cancelled_at IS NOT NULL` の勤怠は、勤務中の一意制約・期間の排他制約・通常履歴用索引から除外する。時刻の前後関係とFKは取消後も有効。
- 作成・操作日時の初期値はDBの `clock_timestamp()`。`updated_at` は更新処理側で明示的に設定する。自動更新トリガーは設けない。
- `before_values=None` はSQLのNULLとして保存する。`after_values` はNOT NULL。スナップショットのキー・UTC文字列表現はAPI側で統一する。
- `work_date`・状態・勤務時間・通知専用テーブルは作成しない。

`session_scope(engine)` 内の処理は同じトランザクションでコミットされ、例外時はまとめてロールバックされる。DB制約違反後のセッションを使い回さない。例：

```python
from app.postgres import session_scope

with session_scope(engine) as session:
    session.add(record)
    session.flush()  # 生成された勤怠IDを取得する
    session.add(audit_log)  # record.idを参照する操作ログ
```

DB制約は勤怠期間の整合性と参照先の存在を保証する。所有者と操作者の一致・ログの追記専用運用・取消の60秒判定・古い画面からの更新検知・通知の排他取得は、#11 / #12 / #14 / #37 のサービス処理で実装する。SQLAlchemyのモデルだけで各APIの業務ルールが完成するわけではない。

## SQLite PoCのデータとdemo-user

SQLiteのPoCデータは元ファイルに保持する。このWBSではSQLiteファイルの読取・変換・削除を自動実行せず、新しいPostgreSQL DBには空の3テーブルを作る。継続利用したいPoCデータがある場合は、元ファイルを保存したうえで移行要否を確認し、別途インポートを行う。過去のサーバー操作日時や変更履歴を捏造して補完しない。

PostgreSQLのデモユーザーは、文字列ID `demo-user` をそのままbigintへ詰め込まず、`users.cognito_sub = 'local:demo-user'` に対応する生成済み `users.id` を利用する。固定IDの `1` は前提にしない。必要なローカルDBに対してだけ次を明示実行する。

```bash
cd backend
python -m app.seed_demo_user
cd ..
```

何度実行しても同じユーザーIDを返し、既存の表示名を上書きしない。マイグレーションやAPI起動時には自動実行しない。この識別値は実際のCognito subとは区別するローカル専用値であり、本番JWT検証でデモ認証へのフォールバックは設けない。既存PoC APIはまだこのPostgreSQLユーザーを参照しない。

## 検証

PostgreSQLを使わない既存テストとオフラインDDL確認：

```bash
python -m pytest -q
```

`BAKURAKU_TEST_DATABASE_URL` がない場合、PostgreSQLのテストはskipとして表示される。skipはDB検証成功を意味しない。

実DBテストは専用DBで実行する。Composeを利用している場合、初回のみテストDBを作る。

```bash
docker compose exec postgres createdb -U bakuraku bakuraku_test
```

```powershell
$env:BAKURAKU_TEST_DATABASE_URL = "postgresql+psycopg://bakuraku:local-dev-only@127.0.0.1:5432/bakuraku_test"
python -m pytest -m postgres -v
python -m pytest -q
```

各実行でランダムな専用スキーマを作成し、その中だけでマイグレーション・初期化・検証・削除を行う。既存スキーマのテーブルは削除しない。`btree_gist` は `public` に導入し、終了時も残す。接続ユーザーにはスキーマ作成と拡張導入の権限が必要。

実DBテストでは、upgradeの再実行、downgrade→upgrade、モデル差分、UTC・DB初期値・IDENTITY、FK・削除拒否、同日再出勤・日跨ぎ・隣接／空区間、重複挿入／修正／同時挿入、取消行の除外、JSONB・修正理由、ログ失敗時の勤怠ロールバック、デモユーザー登録の再実行を確認する。同時挿入では一意／排他制約違反に加え、GiST排他制約の競合で発生し得るデッドロックのロールバックも許容し、コミットは必ず1件だけとなることを検証する。

GitHub Actionsの `Backend tests` ではPostgreSQL 16のサービスとPython 3.11を使い、DB用の環境変数を必ず設定して全pytestを実行する。Vite・Playwright・AWSはこのDB検証には不要。

SQLファイルの生成だけを行う場合：

```bash
python -m alembic -c backend/alembic.ini upgrade head --sql
```

`downgrade base` は3テーブルとその中のデータを削除する。逆向きDDLの確認はテストDB内だけで行う。共有の `btree_gist` 拡張はdowngradeでも削除しない。

## 技術資料

- [SQLAlchemy：PostgreSQL・ExcludeConstraint](https://docs.sqlalchemy.org/en/20/dialects/postgresql.html#sqlalchemy.dialects.postgresql.ExcludeConstraint)
- [Alembic：autogenerateと比較範囲の制限](https://alembic.sqlalchemy.org/en/latest/autogenerate.html)
- [PostgreSQL：範囲型](https://www.postgresql.org/docs/16/rangetypes.html)
