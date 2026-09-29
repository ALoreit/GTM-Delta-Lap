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

        const visible = (node) => {
          if (!node || !node.getClientRects().length) return false;
          const style = getComputedStyle(node);
          return style.display !== "none" && style.visibility !== "hidden";
        };
        const text = (node) => (node?.innerText || "").replace(/\s+/g, " ").trim();
        const firstVisibleText = (selectors) => {
          for (const selector of selectors) {
            const node = document.querySelector(selector);
            if (visible(node) && text(node)) return text(node);
          }
          return "";
        };

        const main = document.querySelector("main");
        if (!main || !visible(main)) return { error: "Das Profil ist noch nicht vollständig geladen." };

        const allowedHeadings = /^(about|über mich|info|experience|berufserfahrung|education|ausbildung|skills|kenntnisse|certifications|lizenzen|zertifikate|projects|projekte|publications|publikationen|volunteering|ehrenamt|honors|auszeichnungen|courses|kurse|languages|sprachen|patents|patente|organizations|organisationen|test scores|testergebnisse)$/i;
        const excludedHeadings = /(people also viewed|people you may know|personen, die sie vielleicht kennen|weitere profile|similar profiles|ähnliche profile)/i;
        const sections = Array.from(main.querySelectorAll("section"))
          .filter(visible)
          .map((section) => {
            const headingNode = section.querySelector("h2");
            const heading = text(headingNode).replace(/\s+(show all|alle anzeigen).*$/i, "").trim();
            const body = text(section);
            return { heading, text: body.slice(0, 6000) };
          })
          .filter((section) => section.heading && allowedHeadings.test(section.heading)
            && !excludedHeadings.test(section.heading) && section.text)
          .filter((section, index, all) => all.findIndex((item) => item.heading.toLowerCase() === section.heading.toLowerCase()) === index)
          .slice(0, 20);

        const experience = sections.find((section) => /^(experience|berufserfahrung)$/i.test(section.heading));
        let company = firstVisibleText([
          "main .pv-text-details__right-panel-item-text",
          "main [data-field='experience_company_logo']",
        ]);
        if (!company && experience) {
          const experienceSection = Array.from(main.querySelectorAll("section"))
            .find((section) => visible(section) && text(section.querySelector("h2")) === experience.heading);
          const firstRole = experienceSection?.querySelector("ul > li");
          const organization = text(firstRole?.querySelector("h4"));
          company = organization.split(/\s+[·|]\s+/)[0].trim();
        }

        return {
          profile_url: profileUrl,
          name: firstVisibleText(["main h1"]),
          headline: firstVisibleText([
            "main .text-body-medium.break-words",
            "main .pv-text-details__left-panel .text-body-medium",
          ]),
          location: firstVisibleText([
            "main .text-body-small.inline.t-black--light.break-words",
            "main .pv-text-details__left-panel .text-body-small",
          ]),
          company,
          profile_data: { sections },
        };
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
  setStatus("Lese sichtbare Profilangaben …");
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
    form.elements.profile_data.value = JSON.stringify(profile.profile_data || { sections: [] }, null, 2);
    const sectionCount = profile.profile_data?.sections?.length || 0;
    setStatus(`Basisangaben und ${sectionCount} sichtbare Profilabschnitte übernommen. Bitte alles prüfen.`, "success");
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

  let profileData;
  try {
    profileData = JSON.parse(data.profile_data || "{\"sections\":[]}");
  } catch {
    setStatus("Die zusätzlichen Profildaten sind kein gültiges JSON. Bitte prüfen.", "error");
    return;
  }
  if (!profileData || typeof profileData !== "object" || Array.isArray(profileData)) {
    setStatus("Die zusätzlichen Profildaten müssen ein JSON-Objekt sein.", "error");
    return;
  }

  submitButton.disabled = true;
  setStatus("Geprüfte Werte werden gespeichert …");
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
