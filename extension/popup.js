const form = document.querySelector("#capture-form");
const submitButton = document.querySelector("#submit");
const importButton = document.querySelector("#import-profile");
const statusBox = document.querySelector("#status");
const API = "http://127.0.0.1:8000";

function setStatus(message, kind = "") {
  statusBox.textContent = message;
  statusBox.className = `status ${kind}`;
}

function currentActiveTab() {
  return new Promise((resolve, reject) => {
    chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
      if (chrome.runtime.lastError) return reject(new Error(chrome.runtime.lastError.message));
      resolve(tabs[0]);
    });
  });
}

function extractVisibleProfile(tabId) {
  return new Promise((resolve, reject) => {
    chrome.scripting.executeScript({
      target: { tabId },
      func: () => {
        const profileUrl = window.location.href;
        if (!/linkedin\.com$/.test(location.hostname) || !location.pathname.startsWith("/in/")) {
          return { error: "Bitte ein einzelnes LinkedIn-Mitgliedsprofil öffnen." };
        }
        const visibleText = (selector) => {
          const node = document.querySelector(selector);
          if (!node || !node.getClientRects().length) return "";
          return (node.innerText || node.textContent || "").replace(/\s+/g, " ").trim();
        };
        const name = visibleText("main h1");
        const headline = visibleText("main .text-body-medium.break-words")
          || visibleText("main [data-generated-suggestion-target]");
        const location = visibleText("main .text-body-small.inline.t-black--light.break-words");
        const company = visibleText("main .pv-text-details__right-panel-item-text");
        return { profile_url: profileUrl, name, headline, location, company };
      }
    }, (results) => {
      if (chrome.runtime.lastError) return reject(new Error(chrome.runtime.lastError.message));
      resolve(results?.[0]?.result || {});
    });
  });
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

importButton.addEventListener("click", async () => {
  importButton.disabled = true;
  setStatus("Lese die im aktiven Profil sichtbaren Basisangaben …");
  try {
    const tab = await currentActiveTab();
    if (!tab?.id || !tab.url || !isLinkedInProfile(tab.url)) {
      setStatus("Der aktive Tab ist kein einzelnes LinkedIn-Mitgliedsprofil.", "error");
      return;
    }
    const profile = await extractVisibleProfile(tab.id);
    if (profile.error) {
      setStatus(profile.error, "error");
      return;
    }
    form.elements.linkedin_url.value = profile.profile_url || tab.url;
    if (profile.name) form.elements.name.value = profile.name;
    if (profile.headline) form.elements.role.value = profile.headline;
    if (profile.location) form.elements.location.value = profile.location;
    if (profile.company && !form.elements.company_name.value) form.elements.company_name.value = profile.company;
    setStatus("Basisangaben übernommen. Bitte alle Werte prüfen und Firmenfelder ergänzen.", "success");
  } catch (error) {
    setStatus(`Import fehlgeschlagen: ${error.message}`, "error");
  } finally {
    importButton.disabled = false;
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
  if (!data.company_name.trim() || !data.domain.trim() || !data.name.trim()) {
    setStatus("Bitte Name, Firmenname und Firmendomain ergänzen.", "error");
    return;
  }

  submitButton.disabled = true;
  setStatus("Werte werden geprüft und gespeichert …");
  try {
    const account = await postJson("/v1/research/accounts", {
      company_name: data.company_name.trim(),
      domain: data.domain.trim(),
      industry: data.industry.trim() || null,
      employee_count: data.employee_count ? Number(data.employee_count) : null,
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
    setStatus(`Nach Prüfung gespeichert. Kontakt-ID: ${contact.contact_id}`, "success");
  } catch (error) {
    setStatus(`Speichern fehlgeschlagen: ${error.message}`, "error");
  } finally {
    submitButton.disabled = false;
  }
});
