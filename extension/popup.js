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
        try {
        const profileUrl = window.location.href;
        const hostname = location.hostname.toLowerCase();
        if (!(hostname === "linkedin.com" || hostname.endsWith(".linkedin.com"))
          || !location.pathname.startsWith("/in/")) {
          return { error: "Bitte ein einzelnes LinkedIn-Mitgliedsprofil öffnen." };
        }

        const visible = (node) => {
          if (!node || !node.getClientRects().length) return false;
          const style = getComputedStyle(node);
          return style.display !== "none"
            && style.visibility !== "hidden"
            && style.opacity !== "0";
        };
        const text = (node) => (node?.innerText || node?.textContent || "").replace(/\s+/g, " ").trim();
        const firstVisibleText = (selectors) => {
          for (const selector of selectors) {
            for (const node of document.querySelectorAll(selector)) {
              if (visible(node) && text(node)) return text(node);
            }
          }
          return "";
        };
        const readContactEmail = () => {
          const dialogRoots = Array.from(document.querySelectorAll("[role='dialog'], .artdeco-modal"))
            .filter(visible);
          const contactOverlay = /\/overlay\/contact-info\/?$/i.test(location.pathname);
          const roots = dialogRoots.length ? dialogRoots : contactOverlay ? [document.body] : [];
          const mailto = roots.flatMap((root) => Array.from(root.querySelectorAll("a[href^='mailto:']")))
            .find((node) => visible(node));
          if (mailto) return decodeURIComponent(mailto.href.replace(/^mailto:/i, "").split("?")[0]);
          const emailPattern = /[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}/i;
          for (const root of roots) {
            const match = text(root).match(emailPattern);
            if (match) return match[0];
          }
          return "";
        };
        const closeContactDialog = () => {
          const closeButton = Array.from(document.querySelectorAll(
            "[role='dialog'] button, .artdeco-modal button, button",
          )).find((node) => visible(node) && (
            /close|schließen/i.test(node.getAttribute("aria-label") || "")
            || /^(close|schließen)$/i.test(text(node))
            || node.classList.contains("artdeco-modal__dismiss")
          ));
          closeButton?.click();
        };

        const main = document.querySelector("main");
        const content = main && visible(main) ? main : document;

        const allowedHeadings = /^(about|über mich|info|experience|erfahrung|berufserfahrung|education|ausbildung|skills|kenntnisse|certifications|lizenzen|zertifikate|projects|projekte|publications|publikationen|volunteering|ehrenamt|honors|auszeichnungen|courses|kurse|languages|sprachen|patents|patente|organizations|organisationen|test scores|testergebnisse)$/i;
        const excludedHeadings = /(people also viewed|people you may know|personen, die sie vielleicht kennen|weitere profile|similar profiles|ähnliche profile)/i;
        const sections = Array.from(content.querySelectorAll("section"))
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

        const profileHeading = main?.querySelector("h1")
          || Array.from(content.querySelectorAll("h1, h2")).find(visible);
        const profileHeader = profileHeading?.closest("section") || content;
        const name = text(profileHeading) || firstVisibleText(["main h1", "h1"]);
        const headerParagraphs = Array.from(profileHeader.querySelectorAll("p"))
          .filter((node) => visible(node) && text(node) && text(node) !== name)
          .map(text);
        const headerHeadline = headerParagraphs
          .find((value) => !/Kontaktinformationen|Kontakte|Metropolregion|He\/Him|Sie\/Ihr|^·\s*\d+\.?$/i.test(value)) || "";
        const headlineSegments = headerHeadline.split(/\s*\|\s*/).map((value) => value.trim()).filter(Boolean);
        const fallbackPosition = headlineSegments.length === 2 ? headlineSegments[1] : "";
        const fallbackCompany = fallbackPosition.match(/@\s*(.+)$/)?.[1]?.trim() || "";
        const headerLocation = headerParagraphs
          .find((value) => /Metropolregion|\b[A-ZÄÖÜ][^,]+,\s*[A-ZÄÖÜ]/i.test(value)
            && !/Kontaktinformationen|Contact information|He\/Him|Sie\/Ihr/i.test(value)) || "";
        const experienceSection = Array.from(content.querySelectorAll("section"))
          .find((section) => visible(section)
            && /^(experience|erfahrung|berufserfahrung)$/i.test(
              text(section.querySelector("h2")).replace(/\s+(show all|alle anzeigen).*$/i, "").trim(),
            ));
        const firstExperienceLink = Array.from(experienceSection?.querySelectorAll("a[href*='/company/']") || [])
          .find((node) => visible(node) && text(node))
          || experienceSection?.querySelector("ul > li");
        const experienceLinkLines = (firstExperienceLink?.innerText || "")
          .split(/\r?\n/).map((line) => line.replace(/\s+/g, " ").trim()).filter(Boolean);
        const isDuration = (value) => /\b(year|years|month|months|jahr|jahre|monat|monate)\b/i.test(value);
        let experienceRole = "";
        let experienceCompany = "";
        if (experienceLinkLines.length >= 2) {
          experienceCompany = experienceLinkLines[1].split(/\s+[·|]\s+/)[0].trim();
          experienceRole = experienceLinkLines[0];
          if (isDuration(experienceLinkLines[1])) {
            experienceCompany = experienceLinkLines[0];
            const sectionLines = (experienceSection?.innerText || "")
              .split(/\r?\n/).map((line) => line.replace(/\s+/g, " ").trim()).filter(Boolean);
            const companyIndex = sectionLines.findIndex((line) => line === experienceCompany);
            experienceRole = companyIndex >= 0 && isDuration(sectionLines[companyIndex + 1] || "")
              ? sectionLines[companyIndex + 2] || "" : "";
          }
        }
        const headline = experienceRole || fallbackPosition;
        const company = experienceCompany || fallbackCompany;
        const companyKey = company.split("(")[0].trim().toLowerCase();
        const companySlug = companyKey.replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
        const matchingCompanyLink = Array.from(content.querySelectorAll("a[href*='/company/']"))
          .find((node) => visible(node) && ((companyKey && text(node).toLowerCase().includes(companyKey))
            || (companySlug && node.href.toLowerCase().includes(`/company/${companySlug}`))));
        const companyUrl = firstExperienceLink?.href || matchingCompanyLink?.href || "";
        const email = readContactEmail();
        const profileLocation = firstVisibleText([
          "main .text-body-small.inline.t-black--light.break-words",
          "main .pv-text-details__left-panel .text-body-small",
        ]) || headerLocation;

        return {
          profile_url: profileUrl,
          name,
          headline,
          location: profileLocation,
          company,
          company_url: companyUrl,
          email,
          profile_data: { sections },
        };
        } catch (error) {
          return { error: `LinkedIn-Seitenskript: ${error?.message || error}` };
        }
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
    if (profile.company_url && !form.elements.domain.value) form.elements.domain.value = profile.company_url;
    if (profile.name) form.elements.name.value = profile.name;
    if (profile.headline) form.elements.role.value = profile.headline;
    if (profile.location) form.elements.location.value = profile.location;
    if (profile.company && !form.elements.company_name.value) form.elements.company_name.value = profile.company;
    if (profile.email) form.elements.email.value = profile.email;
    setStatus("Sichtbare Profilangaben übernommen. Bitte alles prüfen.", "success");
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
    });
    setStatus(`Gespeichert. Review-Aufgabe ${result.review_activity_id || "erstellt"}.`, "success");
  } catch (error) {
    setStatus(`Speichern fehlgeschlagen: ${error.message}`, "error");
  } finally {
    submitButton.disabled = false;
  }
});
