import "./style.css";

const root = document.querySelector("#app");
if (!root) throw new Error("Root element #app is missing");

root.innerHTML = `
  <main class="page">
    <section class="panel" aria-labelledby="app-title">
      <div class="mark" aria-hidden="true">爆</div>
      <p class="eyebrow">Bakuraku Kintai</p>
      <h1 id="app-title">爆楽勤怠</h1>
      <p class="description">勤怠管理を、爆発的にラクに。</p>
      <p class="note">WBS 0.2：プロジェクト雛形。打刻・履歴はこれから実装します。</p>
      <p id="api-status" class="status" role="status">API：接続確認中…</p>
    </section>
  </main>
`;

const apiStatus = document.querySelector("#api-status");

fetch("/api/health")
  .then((response) => {
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return response.json();
  })
  .then((data) => {
    if (data.status !== "ok") throw new Error("Unexpected health response");
    apiStatus.textContent = "API：接続OK";
    apiStatus.classList.add("connected");
  })
  .catch(() => {
    apiStatus.textContent = "API：未接続（バックエンドの起動を確認してください）";
    apiStatus.classList.add("disconnected");
  });
