"""Real Chromium -> Vite -> FastAPI -> isolated PostgreSQL schema (WBS 1.4)."""

import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time
from uuid import uuid4

import httpx
import pytest
from playwright.sync_api import expect, sync_playwright
from sqlalchemy import select, text

from app.models import AttendanceRecord, User
from app.postgres import create_db_engine, get_database_url, session_scope
from app.seed_demo_user import DEMO_COGNITO_SUB

ROOT = Path(__file__).resolve().parents[2]
BASE = "http://127.0.0.1:5173"
pytestmark = [
    pytest.mark.postgres,
    pytest.mark.skipif(not os.environ.get("BAKURAKU_TEST_DATABASE_URL"),
                       reason="Set BAKURAKU_TEST_DATABASE_URL for PostgreSQL browser tests"),
]


class Services:
    def __init__(self, directory, engine):
        self.directory = directory
        self.db_engine = engine
        self.env = {**os.environ,
                    "BAKURAKU_DATABASE_URL": engine.url.render_as_string(hide_password=False)}
        self.api = None
        self.frontend = None
        self.logs = []

    def launch(self, name, command, cwd):
        log = (self.directory / f"{name}.log").open("a", encoding="utf-8")
        self.logs.append(log)
        return subprocess.Popen(command, cwd=cwd, env=self.env, stdout=log,
                                stderr=subprocess.STDOUT)

    def wait_ready(self, process, url):
        deadline = time.monotonic() + 15
        with httpx.Client(trust_env=False, timeout=0.5) as client:
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    break
                try:
                    if client.get(url).status_code == 200:
                        return
                except httpx.HTTPError:
                    pass
                time.sleep(0.05)
        logs = "\n".join(p.read_text(encoding="utf-8")
                         for p in self.directory.glob("*.log"))
        pytest.fail(f"Service did not become ready: {url}\n{logs}")

    def start_api(self):
        self.api = self.launch("api", [sys.executable, "-m", "uvicorn", "app.main:app",
                                      "--host", "127.0.0.1", "--port", "8000"],
                               ROOT / "backend")
        self.wait_ready(self.api, "http://127.0.0.1:8000/api/health/db")

    @staticmethod
    def stop(process):
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)

    def stop_api(self):
        self.stop(self.api)


@pytest.fixture
def e2e_engine():
    url = get_database_url(os.environ["BAKURAKU_TEST_DATABASE_URL"])
    admin = create_db_engine(url)
    schema = "wbs14_e2e_" + uuid4().hex
    engine = None
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    try:
        engine = create_db_engine(url.update_query_dict({"options": f"-csearch_path={schema},public"}))
        yield engine
    finally:
        if engine is not None:
            engine.dispose()
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


@pytest.fixture
def services(tmp_path, e2e_engine):
    # Never connect the suite to a developer's running API or development DB.
    for port in (8000, 5173):
        with socket.socket() as probe:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                probe.bind(("127.0.0.1", port))
                probe.listen(1)
            except OSError:
                pytest.fail(f"Port {port} must be free before running the PoC suite")
    services = Services(tmp_path, e2e_engine)
    try:
        subprocess.run([sys.executable, str(ROOT / "dev.py"), "init-db"],
                       cwd=ROOT, env=services.env, check=True, capture_output=True)
        subprocess.run([sys.executable, str(ROOT / "dev.py"), "seed-demo"],
                       cwd=ROOT, env=services.env, check=True, capture_output=True)
        with session_scope(e2e_engine) as session:
            services.user_id = session.scalar(
                select(User.id).where(User.cognito_sub == DEMO_COGNITO_SUB)
            )
        services.start_api()
        node = shutil.which("node")
        assert node, "Install Node.js before running the PoC suite"
        services.frontend = services.launch(
            "vite", [node, str(ROOT / "frontend/node_modules/vite/bin/vite.js"),
                     "--host", "127.0.0.1", "--port", "5173", "--strictPort"],
            ROOT / "frontend")
        services.wait_ready(services.frontend, BASE + "/api/health/db")
        yield services
    finally:
        services.stop(services.frontend)
        services.stop_api()
        for log in services.logs:
            log.close()


@pytest.fixture(scope="session")
def browser():
    with sync_playwright() as playwright:
        executable = os.environ.get("BAKURAKU_CHROMIUM_PATH")
        browser = playwright.chromium.launch(
            headless=True, **({"executable_path": executable} if executable else {}))
        yield browser
        browser.close()


@pytest.fixture
def page(browser, services, request):
    # A non-JST browser timezone verifies that the UI explicitly formats in JST.
    context = browser.new_context(timezone_id="America/Los_Angeles")
    page = context.new_page()
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    yield page
    artifacts = os.environ.get("BAKURAKU_E2E_ARTIFACT_DIR")
    if artifacts:
        directory = Path(artifacts)
        directory.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(directory / f"{request.node.name}.png"), full_page=True)
    context.close()
    assert not errors, f"Uncaught browser errors: {errors}"


def ready(page, working=False):
    expect(page.locator("#work-status")).to_have_text("勤務中" if working else "勤務外")
    expect(page.locator("#punch")).to_have_text("退勤する" if working else "出勤する")
    expect(page.locator("#punch")).to_be_enabled()


def history(page):
    response = page.request.get(BASE + "/api/attendance/history")
    assert response.status == 200
    return response.json()


@pytest.mark.parametrize("viewport", [{"width": 1280, "height": 900},
                                      {"width": 390, "height": 844}], ids=["desktop", "mobile"])
def test_clock_in_out_history_and_reload(page, viewport):
    page.set_viewport_size(viewport)
    page.goto(BASE)
    ready(page)
    expect(page.locator("#history-message")).to_have_text("まだ打刻履歴はありません。")
    page.get_by_role("button", name="出勤する", exact=True).click()
    ready(page, working=True)
    expect(page.locator(".history-item")).to_have_count(1)
    expect(page.locator(".history-status")).to_have_text("勤務中")
    expect(page.locator(".history-times dd").nth(1)).to_have_text("—")
    original = history(page)[0]
    page.reload()
    ready(page, working=True)
    page.get_by_role("button", name="退勤する", exact=True).click()
    ready(page)
    expect(page.locator(".history-status")).to_have_text("退勤済み")
    finished = history(page)[0]
    assert finished["id"] == original["id"]
    assert finished["clock_in_at"] == original["clock_in_at"]
    assert finished["clock_out_at"] is not None
    page.reload()
    ready(page)
    expect(page.locator(".history-status")).to_have_text("退勤済み")
    assert history(page) == [finished]
    page.locator("#punch").click()
    ready(page, working=True)
    expect(page.locator(".history-item")).to_have_count(2)
    records = history(page)
    assert records[0]["id"] > records[1]["id"] == original["id"]
    expect(page.locator(".history-status").first).to_have_text("勤務中")
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")


def test_api_restart_preserves_active_shift(page, services):
    page.goto(BASE)
    ready(page)
    page.locator("#punch").click()
    ready(page, working=True)
    original = history(page)
    services.stop_api()
    services.start_api()
    page.reload()
    ready(page, working=True)
    assert history(page) == original
    page.locator("#punch").click()
    ready(page)
    assert history(page)[0]["id"] == original[0]["id"]


def test_history_failure_allows_punch_and_recovers(page):
    pattern = "**/api/attendance/history"
    page.route(pattern, lambda route: route.fulfill(status=503, json={"detail": "Database unavailable"}))
    page.goto(BASE)
    ready(page)
    expect(page.locator("#history-message")).to_contain_text("履歴を取得できませんでした")
    page.locator("#punch").click()
    ready(page, working=True)
    expect(page.locator("#history-message")).to_contain_text("履歴を取得できませんでした")
    page.unroute(pattern)
    page.locator("#refresh").click()
    ready(page, working=True)
    expect(page.locator(".history-status")).to_have_text("勤務中")


def test_status_failure_disables_punch_and_recovers(page):
    pattern = "**/api/attendance/status"
    page.route(pattern, lambda route: route.fulfill(status=503, json={"detail": "Database unavailable"}))
    page.goto(BASE)
    expect(page.locator("#error")).to_contain_text("勤務状態を取得できませんでした")
    expect(page.locator("#punch")).to_be_disabled()
    assert history(page) == []
    page.unroute(pattern)
    page.locator("#refresh").click()
    ready(page)


def test_api_outage_and_recovery(page, services):
    page.goto(BASE)
    ready(page)
    services.stop_api()
    page.locator("#refresh").click()
    expect(page.locator("#error")).to_be_visible()
    expect(page.locator("#punch")).to_be_disabled()
    expect(page.locator("#history-message")).to_contain_text("履歴を取得できませんでした")
    services.start_api()
    page.locator("#refresh").click()
    ready(page)
    expect(page.locator("#error")).to_be_hidden()


def test_stale_state_conflict_refreshes_without_duplicate(page):
    page.goto(BASE)
    ready(page)
    response = page.request.post(BASE + "/api/attendance/clock-in")
    assert response.status == 201
    page.locator("#punch").click()  # stale UI still offers clock-in
    ready(page, working=True)
    expect(page.locator("#error")).to_contain_text("勤務状態が更新されていました")
    assert history(page) == [response.json()]


def test_lost_post_response_is_not_retried(page):
    posts = []

    def lose_response(route):
        posts.append(route.request.url)
        assert route.fetch().status == 201  # actually persist through Vite and FastAPI
        route.abort("failed")  # browser cannot tell whether the write succeeded

    page.route("**/api/attendance/clock-in", lose_response)
    page.goto(BASE)
    ready(page)
    page.locator("#punch").click()
    ready(page, working=True)
    expect(page.locator("#error")).to_contain_text("通信結果を確認できませんでした")
    assert len(posts) == 1
    assert len(history(page)) == 1
    expect(page.locator(".history-status")).to_have_text("勤務中")


def test_rapid_clicks_send_one_post(page):
    posts = []
    page.on("request", lambda request: posts.append(request.url)
            if request.method == "POST" else None)
    page.goto(BASE)
    ready(page)
    page.locator("#punch").evaluate("button => { button.click(); button.click(); }")
    ready(page, working=True)
    assert len(posts) == 1
    assert len(history(page)) == 1


@pytest.mark.parametrize("start,expected_date,expected_time", [
    ("2026-10-20T14:30:00+00:00", "2026年10月20日", "23:30"),
    ("2026-10-20T23:30:00+00:00", "2026年10月21日", "08:30"),
], ids=["jst-midnight", "utc-midnight"])
def test_overnight_shift_and_jst_display(page, services, start, expected_date, expected_time):
    # Old fixture data is deliberate: crossing dates and exceeding 16h must not close a shift.
    from datetime import datetime

    with session_scope(services.db_engine) as session:
        session.add(AttendanceRecord(user_id=services.user_id,
                                     clock_in_at=datetime.fromisoformat(start)))
    page.goto(BASE)
    ready(page, working=True)
    expect(page.locator(".history-item-heading time")).to_contain_text(expected_date)
    expect(page.locator(".history-times dd").first).to_have_text(expected_time)
    expect(page.locator(".history-times dd").nth(1)).to_have_text("—")
    assert history(page)[0]["clock_out_at"] is None
    page.locator("#punch").click()
    ready(page)
    expect(page.locator(".history-status")).to_have_text("退勤済み")
    assert history(page)[0]["clock_out_at"] is not None
