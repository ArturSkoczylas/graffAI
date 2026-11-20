const DEFAULT_BACKEND_URL = "http://127.0.0.1:8765/draft";

async function getBackendUrl() {
  const stored = await messenger.storage.local.get("backendUrl");
  return stored.backendUrl || DEFAULT_BACKEND_URL;
}

async function setBadge(tabId, text, color) {
  await messenger.messageDisplayAction.setBadgeText({ tabId, text });
  if (color) {
    await messenger.messageDisplayAction.setBadgeBackgroundColor({ tabId, color });
  }
}

async function notify(title, message) {
  await messenger.notifications.create({ type: "basic", title, message });
}

messenger.messageDisplayAction.onClicked.addListener(async (tab) => {
  const tabId = tab.id;
  try {
    await setBadge(tabId, "...", "#888888");

    const message = await messenger.messageDisplay.getDisplayedMessage(tabId);
    if (!message) {
      throw new Error("Brak otwartej wiadomości w tej karcie.");
    }

    const raw = await messenger.messages.getRaw(message.id);
    const backendUrl = await getBackendUrl();

    const response = await fetch(backendUrl, {
      method: "POST",
      headers: { "Content-Type": "message/rfc822" },
      body: raw,
    });
    const payload = await response.json().catch(() => ({}));

    if (!response.ok) {
      throw new Error(payload.message || `Serwer odpowiedział ${response.status}`);
    }

    await setBadge(tabId, "OK", "#2e7d32");
    await notify("Szkic gotowy", `Temat: ${payload.subject || "(brak)"} – sprawdź folder Szkice.`);
  } catch (err) {
    await setBadge(tabId, "!", "#c62828");
    await notify("Nie udało się wygenerować szkicu", err && err.message ? err.message : String(err));
  } finally {
    setTimeout(() => setBadge(tabId, ""), 4000);
  }
});
