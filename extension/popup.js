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
        const hostname = location.hostname.toLowerCase();
        if (!(hostname === "linkedin.com" || hostname.endsWith(".linkedin.com"))
          || !location.pathname.startsWith("/in/")) {
          return { error: "Bitte ein einzelnes LinkedIn-Mitgliedsprofil öffnen." };
        }
        const visibleText = (selectors) => {
          for (const selector of selectors) {
            const node = document.querySelector(selector);
            if (!node || !node.getClientRects().length) continue;
            const value = (node.innerText || node.textContent || "").replace(/\s+/g, " ").trim();
            if (value) return value;
          }
          return "";
        };
        const name = visibleText(["main h1"]);
        const headline = visibleText([
          "main .text-body-medium.break-words",
          "main .pv-text-details__left-panel .text-body-medium",
          "main [data-generated-suggestion-target]",
        ]);
        const location = visibleText([
          "main .text-body-small.inline.t-black--light.break-words",
          "main .pv-text-details__left-panel .text-body-small",
        ]);
        const company = visibleText([
          "main .pv-text-details__right-panel-item-text",
          "main .pv-text-details__left-panel .inline-show-more-text",
        ]);
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
    setStatus("Sichtbare Basisangaben übernommen. Bitte die Werte prüfen und Firmenfelder ergänzen.", "success");
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
    const result = await postJson("/v1/import/linkedin-visible-profile", {
      user_confirmed: true,
      company_name: data.company_name.trim(),
      domain: data.domain.trim(),
      industry: data.industry.trim() || null,
      employee_count: data.employee_count ? Number(data.employee_count) : null,
      country: "DACH",
      name: data.name.trim(),
      role: data.role.trim() || null,
      profile_location: data.location.trim() || null,
      email: data.email.trim() || null,
      phone: data.phone.trim() || null,
      linkedin_url: data.linkedin_url.trim(),
    });
    setStatus(`Kontakt gespeichert und zur Prüfung vorgemerkt. Kontakt-ID: ${result.contact_id}`, "success");
  } catch (error) {
    setStatus(`Speichern fehlgeschlagen: ${error.message}`, "error");
  } finally {
    submitButton.disabled = false;
  }
});
