import "./style.css";

const root = document.querySelector("#app");
if (!root) throw new Error("Root element #app is missing");

root.innerHTML = `
  <div class="shell">
    <header class="header">
      <a class="brand" href="/" aria-label="爆楽勤怠 ホーム">
        <span class="mark" aria-hidden="true">爆</span>
        <span>爆楽勤怠<small>Bakuraku Kintai</small></span>
      </a>
      <span class="demo">デモユーザー</span>
    </header>
    <main class="page">
      <div class="intro"><p class="eyebrow">HOME</p><h1>今日も、おつかれさまです。</h1>
        <p>いつもの一日を、ワンタッチで。</p></div>
      <section class="panel" aria-labelledby="clock-title">
        <div class="panel-heading"><h2 id="clock-title">出退勤の打刻</h2>
          <span id="work-status" class="status" aria-live="polite">確認中</span></div>
        <p id="today" class="today"></p>
        <p id="clock" class="clock" aria-label="現在時刻（日本時間）"></p>
        <p class="timezone">日本時間（JST）</p>
        <p id="guidance" class="guidance">勤務状態を確認しています。</p>
        <button id="punch" class="punch" type="button" disabled>状態確認中…</button>
        <dl class="shift"><dt>出勤時刻</dt><dd id="clock-in-time">—</dd></dl>
        <p id="notice" class="notice" role="status"></p>
        <p id="error" class="error" role="alert" hidden></p>
        <button id="refresh" class="refresh" type="button">状態・履歴を再確認</button>
      </section>
      <section id="history-panel" class="history-panel" aria-labelledby="history-title">
        <div class="history-heading">
          <h2 id="history-title">打刻履歴</h2><span>新しい順</span>
        </div>
        <p id="history-message" class="history-message" role="status">履歴を読み込んでいます。</p>
        <ol id="history-list" class="history-list"></ol>
      </section>
      <p class="footnote">固定のデモユーザーで操作します。<br>打刻時刻はサーバーで記録されます。</p>
    </main>
    <footer>勤怠管理を、爆発的にラクに。</footer>
  </div>
`;

const elements = Object.fromEntries([
  "work-status", "today", "clock", "guidance", "punch", "clock-in-time",
  "notice", "error", "refresh", "history-panel", "history-message", "history-list",
].map((id) => [id, document.getElementById(id)]));

let attendance = null; // null means that the server state is unknown.
let attendanceHistory = null;
let historyError = "";
let busy = false;
const dateFormat = new Intl.DateTimeFormat("ja-JP", {
  timeZone: "Asia/Tokyo", year: "numeric", month: "long", day: "numeric", weekday: "long",
});
const timeFormat = new Intl.DateTimeFormat("ja-JP", {
  timeZone: "Asia/Tokyo", hour: "2-digit", minute: "2-digit", second: "2-digit", hourCycle: "h23",
});
const punchFormat = new Intl.DateTimeFormat("ja-JP", {
  timeZone: "Asia/Tokyo", year: "numeric", month: "2-digit", day: "2-digit",
  hour: "2-digit", minute: "2-digit", hourCycle: "h23",
});
const historyDateFormat = new Intl.DateTimeFormat("ja-JP", {
  timeZone: "Asia/Tokyo", year: "numeric", month: "long", day: "numeric", weekday: "short",
});
const historyTimeFormat = new Intl.DateTimeFormat("ja-JP", {
  timeZone: "Asia/Tokyo", hour: "2-digit", minute: "2-digit", hourCycle: "h23",
});

function updateClock() {
  const now = new Date();
  elements.today.textContent = dateFormat.format(now);
  elements.clock.textContent = timeFormat.format(now);
}
updateClock();
setInterval(updateClock, 1000);

function render() {
  const working = attendance?.status === "working";
  elements["work-status"].textContent = attendance ? (working ? "勤務中" : "勤務外") : "状態未確認";
  elements["work-status"].classList.toggle("working", working);
  elements.punch.disabled = busy || !attendance;
  elements.punch.setAttribute("aria-busy", String(busy));
  elements.punch.classList.toggle("clock-out", working);
  elements.punch.textContent = busy ? "確認・通信中…" : attendance ? (working ? "退勤する" : "出勤する") : "状態を確認してください";
  elements.guidance.textContent = attendance
    ? (working ? "勤務中です。お帰りの際に退勤を打刻してください。" : "準備ができたら、出勤を打刻しましょう。")
    : "状態を再確認してから、打刻できます。";
  elements["clock-in-time"].textContent = working
    ? punchFormat.format(new Date(attendance.active_record.clock_in_at)) : "—";
  elements.refresh.disabled = busy;
}

function historyItem(record) {
  const item = document.createElement("li");
  item.className = "history-item";

  const heading = document.createElement("div");
  heading.className = "history-item-heading";
  const date = document.createElement("time");
  date.dateTime = record.clock_in_at;
  date.textContent = historyDateFormat.format(new Date(record.clock_in_at));
  const status = document.createElement("span");
  status.className = record.clock_out_at ? "history-status" : "history-status working";
  status.textContent = record.clock_out_at ? "退勤済み" : "勤務中";
  heading.append(date, status);

  const times = document.createElement("dl");
  times.className = "history-times";
  for (const [label, value] of [
    ["出勤", record.clock_in_at], ["退勤", record.clock_out_at],
  ]) {
    const term = document.createElement("dt");
    term.textContent = label;
    const detail = document.createElement("dd");
    if (value) {
      const time = document.createElement("time");
      time.dateTime = value;
      time.textContent = historyTimeFormat.format(new Date(value));
      detail.append(time);
    } else {
      detail.textContent = "—";
    }
    times.append(term, detail);
  }
  item.append(heading, times);
  return item;
}

function renderHistory() {
  elements["history-panel"].setAttribute("aria-busy", String(busy && attendanceHistory === null));
  elements["history-list"].replaceChildren();
  if (attendanceHistory === null) {
    elements["history-message"].hidden = false;
    elements["history-message"].classList.toggle("error-text", Boolean(historyError));
    elements["history-message"].textContent = historyError || "履歴を読み込んでいます。";
    return;
  }
  elements["history-message"].classList.remove("error-text");
  if (attendanceHistory.length === 0) {
    elements["history-message"].hidden = false;
    elements["history-message"].textContent = "まだ打刻履歴はありません。";
    return;
  }
  elements["history-message"].hidden = true;
  elements["history-list"].append(...attendanceHistory.map(historyItem));
}

function showError(message = "") {
  elements.error.textContent = message;
  elements.error.hidden = !message;
}

async function request(path, method = "GET") {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 10000);
  try {
    const response = await fetch(`/api/attendance/${path}`, {
      method, signal: controller.signal, cache: "no-store",
    });
    if (!response.ok) {
      const error = new Error(`HTTP ${response.status}`);
      error.status = response.status;
      throw error;
    }
    return await response.json();
  } finally {
    clearTimeout(timeout);
  }
}

async function readStatus() {
  const data = await request("status");
  if (!["not_working", "working"].includes(data.status)
      || (data.status === "working" && (!data.active_record
          || typeof data.active_record.clock_in_at !== "string"
          || Number.isNaN(Date.parse(data.active_record.clock_in_at))))) {
    throw new Error("Unexpected attendance response");
  }
  attendance = data;
}

async function readHistory() {
  const data = await request("history");
  const isTimestamp = (value) => typeof value === "string" && !Number.isNaN(Date.parse(value));
  if (!Array.isArray(data) || !data.every((record) => record
      && Number.isInteger(record.id)
      && Number.isSafeInteger(record.user_id) && record.user_id > 0
      && isTimestamp(record.clock_in_at)
      && (record.clock_out_at === null || isTimestamp(record.clock_out_at)))) {
    throw new Error("Unexpected attendance history response");
  }
  attendanceHistory = data;
  historyError = "";
}

async function readHistorySafely() {
  attendanceHistory = null;
  historyError = "";
  try {
    await readHistory();
  } catch {
    historyError = "履歴を取得できませんでした。「状態・履歴を再確認」を押してください。";
  }
}

async function refreshStatus() {
  if (busy) return;
  busy = true;
  attendance = null;
  attendanceHistory = null;
  historyError = "";
  elements.notice.textContent = "";
  showError();
  render();
  renderHistory();
  const [statusResult, historyResult] = await Promise.allSettled([readStatus(), readHistory()]);
  if (statusResult.status === "rejected") {
    showError("勤務状態を取得できませんでした。API・DBの起動を確認し、「状態・履歴を再確認」を押してください。");
  }
  if (historyResult.status === "rejected") {
    historyError = "履歴を取得できませんでした。API・DBの起動を確認してください。";
  }
  busy = false;
  render();
  renderHistory();
}

async function punch() {
  if (busy || !attendance) return;
  const working = attendance.status === "working";
  const action = working ? "clock-out" : "clock-in";
  const label = working ? "退勤" : "出勤";
  busy = true; // Lock immediately, before the first asynchronous operation.
  elements.notice.textContent = "";
  showError();
  render();
  let recorded = false;
  try {
    await request(action, "POST");
    recorded = true;
    attendance = null;
    await readStatus();
    elements.notice.textContent = `${label}を記録しました。${working ? "今日も一日、おつかれさまでした。" : "いってらっしゃい！"}`;
  } catch (error) {
    attendance = null;
    // A failed POST may have reached the server. Never retry a punch automatically.
    try {
      await readStatus();
      showError(error.status === 409
        ? "勤務状態が更新されていました。最新の状態と出勤時刻を確認してください。"
        : recorded ? `${label}は記録されました。最新の勤務状態を再取得しました。`
          : "通信結果を確認できませんでした。最新の勤務状態を表示しています。再度押す前に状態と出勤時刻を確認してください。");
    } catch {
      showError(recorded
        ? `${label}は記録されましたが、勤務状態を取得できません。「状態・履歴を再確認」を押してください。`
        : "打刻結果を確認できません。再送せず、「状態・履歴を再確認」で勤務状態を確認してください。");
    }
  } finally {
    await readHistorySafely();
    busy = false;
    render();
    renderHistory();
  }
}

elements.punch.addEventListener("click", punch);
elements.refresh.addEventListener("click", refreshStatus);
renderHistory();
void refreshStatus();
