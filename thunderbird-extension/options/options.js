const DEFAULT_BACKEND_URL = "http://127.0.0.1:8765/draft";

async function load() {
  const { backendUrl } = await messenger.storage.local.get("backendUrl");
  document.getElementById("url").value = backendUrl || DEFAULT_BACKEND_URL;
}

document.getElementById("form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const url = document.getElementById("url").value.trim() || DEFAULT_BACKEND_URL;
  await messenger.storage.local.set({ backendUrl: url });
  document.getElementById("status").textContent = "Zapisano.";
});

load();
