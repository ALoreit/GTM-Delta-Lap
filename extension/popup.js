const form = document.querySelector("#capture-form");
const button = document.querySelector("#submit");
const useTabButton = document.querySelector("#use-tab");
const statusBox = document.querySelector("#status");
const API = "http://127.0.0.1:8000";

function setStatus(message, kind = "") {
  statusBox.textContent = message;
  statusBox.className = `status ${kind}`;
}

function isLinkedInProfile(value) {
  try {
    const url = new URL(value);
    return (url.hostname === "linkedin.com" || url.hostname.endsWith(".linkedin.com"))
      && url.pathname.startsWith("/in/");
  } catch {
    return false;
  }
}

useTabButton.addEventListener("click", async () => {
  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (!tab?.url || !isLinkedInProfile(tab.url)) {
      setStatus("Der aktive Tab scheint kein individuelles LinkedIn-Profil zu sein.", "error");
      return;
    }
    form.elements.linkedin_url.value = tab.url;
    setStatus("URL übernommen. Bitte alle übrigen Angaben selbst prüfen/eintragen.", "success");
  } catch {
    setStatus("Tab-URL konnte nicht übernommen werden. Bitte manuell einfügen.", "error");
  }
});

async function postJson(path, body) {
  const response = await fetch(`${API}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = typeof payload.detail === "string" ? payload.detail : `HTTP ${response.status}`;
    throw new Error(detail);
  }
  return payload;
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const data = Object.fromEntries(new FormData(form).entries());
  if (!isLinkedInProfile(data.linkedin_url)) {
    setStatus("Bitte eine LinkedIn-Profil-URL im Format linkedin.com/in/... prüfen.", "error");
    return;
  }

  button.disabled = true;
  setStatus("Account wird gespeichert …");
  try {
    const account = await postJson("/v1/research/accounts", {
      company_name: data.company_name.trim(),
      domain: data.domain.trim(),
      industry: data.industry.trim() || null,
      country: "DACH",
      signals: [],
    });
    const contact = await postJson(`/v1/accounts/${account.account_id}/contacts`, {
      name: data.name.trim(),
      role: data.role.trim() || null,
      email: data.email.trim() || null,
      phone: data.phone.trim() || null,
      linkedin_url: data.linkedin_url.trim(),
      source_url: data.linkedin_url.trim(),
      source_type: "manual_link",
    });
    setStatus(`Kontakt manuell erfasst und zur Prüfung vorgemerkt (${contact.contact_id}).`, "success");
    form.reset();
  } catch (error) {
    setStatus(`Speichern fehlgeschlagen: ${error.message}`, "error");
  } finally {
    button.disabled = false;
  }
});
