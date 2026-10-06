const state = { contactId: null, sort: "company", direction: "asc" };
const $ = (id) => document.getElementById(id);
const escapeHtml = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;" }[char]));
const formatDate = (value) => value ? new Date(value).toLocaleString("de-DE", { dateStyle: "medium", timeStyle: "short" }) : "kein Termin";

async function request(path, options = {}) {
  const response = await fetch(path, { headers: { "Content-Type": "application/json" }, ...options });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail || `Anfrage fehlgeschlagen (${response.status})`);
  }
  return response.json();
}

async function loadContacts() {
  $("list-status").textContent = "";
  try {
    const params = new URLSearchParams();
    const search = $("search").value.trim();
    if (search) params.set("search", search);
    params.set("sort", state.sort);
    params.set("direction", state.direction);
    const data = await request(`/v1/contacts?${params.toString()}`);
    $("count").textContent = `${data.items.length} Kontakte`;
    $("contact-rows").innerHTML = data.items.length ? data.items.map((contact) =>
      `<tr data-id="${escapeHtml(contact.id)}"><td>${escapeHtml(contact.company_name)}</td><td>${escapeHtml(contact.name)}</td><td>${escapeHtml(contact.role || "—")}</td><td><button class="toggle ${contact.linkedin_connected ? "active" : ""}" type="button" data-linkedin-id="${escapeHtml(contact.id)}" aria-pressed="${contact.linkedin_connected}">${contact.linkedin_connected ? "Ja" : "Nein"}</button></td></tr>`
    ).join("") : `<tr><td colspan="4" class="muted">Keine Kontakte gefunden.</td></tr>`;
    document.querySelectorAll("#contact-rows tr[data-id]").forEach((row) => row.addEventListener("click", (event) => {
      if (!event.target.closest("[data-linkedin-id], [data-sort]")) showContact(row.dataset.id);
    }));
    document.querySelectorAll("[data-linkedin-id]").forEach((button) => button.addEventListener("click", () => toggleLinkedIn(button)));
  } catch (error) { $("list-status").textContent = error.message; }
}

function updateSortButtons() {
  document.querySelectorAll("[data-sort]").forEach((button) => {
    const active = button.dataset.sort === state.sort;
    button.classList.toggle("active", active);
    button.querySelector("span").textContent = active && state.direction === "desc" ? "↓" : "↑";
    button.setAttribute("aria-label", `${button.textContent.trim()} sortieren`);
  });
  $("sort-added").querySelector("span").textContent = state.sort === "added" && state.direction === "desc" ? "↓" : "↑";
}

function toggleSort(sort) {
  if (state.sort === sort) state.direction = state.direction === "asc" ? "desc" : "asc";
  else { state.sort = sort; state.direction = "asc"; }
  updateSortButtons();
  loadContacts();
}

async function toggleLinkedIn(button) {
  button.disabled = true;
  try {
    const connected = button.getAttribute("aria-pressed") !== "true";
    const result = await request(`/v1/contacts/${encodeURIComponent(button.dataset.linkedinId)}/linkedin-connected?connected=${connected}`, { method: "PATCH" });
    button.classList.toggle("active", result.linkedin_connected);
    button.setAttribute("aria-pressed", result.linkedin_connected);
    button.textContent = result.linkedin_connected ? "Ja" : "Nein";
  } catch (error) {
    $("list-status").textContent = error.message;
  } finally {
    button.disabled = false;
  }
}

async function showContact(id) {
  state.contactId = id;
  $("list-view").classList.add("hidden"); $("detail-view").classList.remove("hidden");
  $("contact-detail").innerHTML = "<p class='muted'>Lade Kontakt …</p>";
  try {
    const contact = await request(`/v1/contacts/${encodeURIComponent(id)}`);
    const value = (item, fallback = "Fehlt") => item !== null && item !== undefined && item !== "" ? escapeHtml(item) : `<span class="missing">${fallback}</span>`;
    $("contact-detail").innerHTML = `<div class="contact-head"><div><h2>${value(contact.name)}</h2><p>${value(contact.role)} · ${value(contact.company.name)}</p></div><div class="contact-meta">${contact.linkedin_connected ? '<span class="connected">✓ Auf LinkedIn vernetzt</span>' : '<span class="missing">Nicht als vernetzt markiert</span>'}<br>${contact.linkedin_url ? `<a href="${escapeHtml(contact.linkedin_url)}" target="_blank" rel="noreferrer">LinkedIn-Profil öffnen</a>` : '<span class="missing">LinkedIn-URL fehlt</span>'}</div></div><div class="info-grid"><div><h3>Kontakt</h3><dl><dt>Name</dt><dd>${value(contact.name)}</dd><dt>Position</dt><dd>${value(contact.role)}</dd><dt>Standort</dt><dd>${value(contact.location)}</dd><dt>E-Mail</dt><dd>${contact.email ? `<a href="mailto:${escapeHtml(contact.email)}">${escapeHtml(contact.email)}</a>` : '<span class="missing">Fehlt</span>'}</dd><dt>Telefon</dt><dd>${value(contact.phone)}</dd><dt>LinkedIn vernetzt</dt><dd>${contact.linkedin_connected ? "Ja" : "Nein"}</dd></dl></div><div><h3>Firma</h3><dl><dt>Firma</dt><dd>${value(contact.company.name)}</dd><dt>Domain</dt><dd>${value(contact.company.domain)}</dd><dt>Branche</dt><dd>${value(contact.company.industry)}</dd><dt>Mitarbeitende</dt><dd>${value(contact.company.employee_count)}</dd><dt>Land/Region</dt><dd>${value(contact.company.country)}</dd><dt>ICP-Score</dt><dd>${value(contact.company.icp_score)}</dd><dt>Review-Status</dt><dd>${value(contact.company.review_status)}</dd></dl></div><div><h3>Herkunft</h3><dl><dt>Quelle</dt><dd>${value(contact.source_type)}</dd><dt>Quell-URL</dt><dd>${contact.source_url ? `<a href="${escapeHtml(contact.source_url)}" target="_blank" rel="noreferrer">Öffnen</a>` : '<span class="missing">Fehlt</span>'}</dd><dt>Letzte Prüfung</dt><dd>${contact.last_verified_at ? formatDate(contact.last_verified_at) : '<span class="missing">Fehlt</span>'}</dd><dt>Angelegt</dt><dd>${formatDate(contact.created_at)}</dd></dl></div></div>`;
    $("edit-name").value = contact.name || "";
    $("edit-role").value = contact.role || "";
    $("edit-location").value = contact.location || "";
    $("edit-email").value = contact.email || "";
    $("edit-phone").value = contact.phone || "";
    $("edit-linkedin-url").value = contact.linkedin_url || "";
    $("edit-linkedin-connected").checked = contact.linkedin_connected;
    $("edit-company-name").value = contact.company.name || "";
    $("edit-domain").value = contact.company.domain || "";
    $("edit-industry").value = contact.company.industry || "";
    $("edit-employee-count").value = contact.company.employee_count ?? "";
    $("edit-country").value = contact.company.country || "DACH";
    $("notes").innerHTML = contact.notes.length ? contact.notes.map((note) => `<article class="entry"><p>${escapeHtml(note.body)}</p><small>${formatDate(note.created_at)}</small></article>`).join("") : `<p class="muted">Noch keine Notizen.</p>`;
    $("actions").innerHTML = contact.actions.length ? contact.actions.map((action) => `<article class="entry"><strong>${escapeHtml(action.title)}</strong><p>${escapeHtml(action.details || "")}</p><small>${action.status} · ${formatDate(action.due_at)}</small></article>`).join("") : `<p class="muted">Noch keine geplanten Aktionen.</p>`;
  } catch (error) { $("contact-detail").innerHTML = `<p class="status">${escapeHtml(error.message)}</p>`; }
}

$("edit-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  $("edit-status").textContent = "";
  const employeeCount = $("edit-employee-count").value;
  try {
    await request(`/v1/contacts/${encodeURIComponent(state.contactId)}`, {
      method: "PATCH",
      body: JSON.stringify({
        name: $("edit-name").value,
        role: $("edit-role").value || null,
        profile_location: $("edit-location").value || null,
        email: $("edit-email").value || null,
        phone: $("edit-phone").value || null,
        linkedin_url: $("edit-linkedin-url").value || null,
        linkedin_connected: $("edit-linkedin-connected").checked,
        company_name: $("edit-company-name").value,
        domain: $("edit-domain").value,
        industry: $("edit-industry").value || null,
        employee_count: employeeCount ? Number(employeeCount) : null,
        country: $("edit-country").value,
      }),
    });
    $("edit-status").className = "status success";
    $("edit-status").textContent = "Änderungen gespeichert.";
    await showContact(state.contactId);
  } catch (error) {
    $("edit-status").className = "status";
    $("edit-status").textContent = error.message;
  }
});

$("search").addEventListener("input", loadContacts);
$("sort-added").addEventListener("click", () => toggleSort("added"));
document.querySelectorAll("[data-sort]").forEach((button) => button.addEventListener("click", () => toggleSort(button.dataset.sort)));
$("refresh").addEventListener("click", loadContacts);
$("back").addEventListener("click", () => { state.contactId = null; $("detail-view").classList.add("hidden"); $("list-view").classList.remove("hidden"); loadContacts(); });
$("note-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  try { await request(`/v1/contacts/${state.contactId}/notes`, { method: "POST", body: JSON.stringify({ body: $("note-body").value }) }); $("note-body").value = ""; await showContact(state.contactId); }
  catch (error) { alert(error.message); }
});
$("action-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    const due = $("action-due").value;
    await request(`/v1/contacts/${state.contactId}/actions`, { method: "POST", body: JSON.stringify({ title: $("action-title").value, details: $("action-details").value || null, due_at: due ? new Date(due).toISOString() : null }) });
    $("action-form").reset(); await showContact(state.contactId);
  } catch (error) { alert(error.message); }
});
updateSortButtons();
loadContacts();
