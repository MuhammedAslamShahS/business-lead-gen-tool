const STORAGE_KEY = "leadgen.homeState";

const searchForm = document.getElementById("search-form");
const countryInput = document.getElementById("country");
const stateInput = document.getElementById("state");
const districtInput = document.getElementById("district");
const cityInput = document.getElementById("city");
const limitInput = document.getElementById("limit");
const searchButton = document.getElementById("search-button");
const uploadButton = document.getElementById("upload-button");
const messageEl = document.getElementById("message");
const resultsBody = document.getElementById("results-body");
const resultsMeta = document.getElementById("results-meta");
const leadSearchInput = document.getElementById("lead-search");
const leadSuggestions = document.getElementById("lead-suggestions");

let currentLeads = [];
let filteredLeads = [];
let currentLocationContext = null;
let currentSummary = "";

function setMessage(text, tone = "") {
  messageEl.textContent = text;
  messageEl.className = tone ? `message ${tone}` : "message";
}

function linkOrText(value) {
  if (!value || value === "Not available") {
    return "Not available";
  }
  const safeValue = String(value);
  return `<a href="${safeValue}" target="_blank" rel="noopener noreferrer">${safeValue}</a>`;
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function searchableText(lead) {
  return [
    lead.name || "",
    lead.phone || "",
    lead.location || "",
    lead.email || "",
    lead.website || "",
  ].join(" ").toLowerCase();
}

function suggestionItems(leads, query) {
  const normalized = query.trim().toLowerCase();
  if (!normalized) {
    return [];
  }

  const items = [];
  const seen = new Set();
  for (const lead of leads) {
    const candidates = [
      { label: lead.name, meta: "Business" },
      { label: lead.phone, meta: "Phone" },
      { label: lead.location, meta: "Location" },
    ];

    for (const candidate of candidates) {
      const label = candidate.label || "";
      if (!label || label === "Not available") {
        continue;
      }
      if (!label.toLowerCase().includes(normalized)) {
        continue;
      }
      const key = `${candidate.meta}:${label.toLowerCase()}`;
      if (seen.has(key)) {
        continue;
      }
      seen.add(key);
      items.push({
        value: label,
        meta: candidate.meta,
      });
      if (items.length >= 8) {
        return items;
      }
    }
  }
  return items;
}

function hideSuggestions() {
  leadSuggestions.hidden = true;
  leadSuggestions.innerHTML = "";
}

function renderSuggestions(query) {
  const items = suggestionItems(currentLeads, query);
  if (!items.length) {
    hideSuggestions();
    return;
  }

  leadSuggestions.innerHTML = items.map((item) => `
    <button class="suggestion-item" type="button" data-value="${escapeHtml(item.value)}">
      <span>${escapeHtml(item.value)}</span>
      <small>${escapeHtml(item.meta)}</small>
    </button>
  `).join("");
  leadSuggestions.hidden = false;
}

function applyLeadFilter() {
  const query = leadSearchInput.value.trim().toLowerCase();
  filteredLeads = query
    ? currentLeads.filter((lead) => searchableText(lead).includes(query))
    : [...currentLeads];

  renderRows(filteredLeads);

  if (!currentLeads.length) {
    resultsMeta.textContent = currentSummary || "Search by location to generate public business leads.";
    return;
  }

  if (!query) {
    resultsMeta.textContent = currentSummary;
  } else {
    resultsMeta.textContent = `${filteredLeads.length} matching leads from ${currentLeads.length} generated results.`;
  }
}

function renderRows(leads) {
  if (!leads.length) {
    resultsBody.innerHTML = `
      <tr class="empty-row">
        <td colspan="6">No leads found for this search.</td>
      </tr>
    `;
    return;
  }

  resultsBody.innerHTML = leads.map((lead) => {
    const socials = Object.entries(lead.socials || {})
      .map(([label, value]) => `<li><strong>${label}:</strong> ${linkOrText(value)}</li>`)
      .join("");

    return `
      <tr>
        <td>${escapeHtml(lead.name || "Not available")}</td>
        <td>${escapeHtml(lead.location || "Not available")}</td>
        <td>${escapeHtml(lead.phone || "Not available")}</td>
        <td>${escapeHtml(lead.email || "Not available")}</td>
        <td>${linkOrText(lead.website)}</td>
        <td><ul class="social-list">${socials}</ul></td>
      </tr>
    `;
  }).join("");
}

function saveState() {
  const state = {
    form: {
      country: countryInput.value,
      state: stateInput.value,
      district: districtInput.value,
      city: cityInput.value,
      limit: limitInput.value,
      leadSearch: leadSearchInput.value,
    },
    currentLeads,
    currentLocationContext,
    currentSummary,
    message: {
      text: messageEl.textContent,
      tone: messageEl.className.replace("message", "").trim(),
    },
  };
  localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
}

function restoreState() {
  const raw = localStorage.getItem(STORAGE_KEY);
  if (!raw) {
    return;
  }

  try {
    const saved = JSON.parse(raw);
    const form = saved.form || {};
    countryInput.value = form.country || countryInput.value;
    stateInput.value = form.state || stateInput.value;
    districtInput.value = form.district || districtInput.value;
    cityInput.value = form.city || cityInput.value;
    limitInput.value = form.limit || limitInput.value;
    leadSearchInput.value = form.leadSearch || "";

    currentLeads = Array.isArray(saved.currentLeads) ? saved.currentLeads : [];
    currentLocationContext = saved.currentLocationContext || null;
    currentSummary = saved.currentSummary || "";

    if (saved.message?.text) {
      setMessage(saved.message.text, saved.message.tone || "");
    }

    uploadButton.disabled = currentLeads.length === 0;
    applyLeadFilter();
  } catch (error) {
    localStorage.removeItem(STORAGE_KEY);
  }
}

async function handleSearch(event) {
  event.preventDefault();
  const country = countryInput.value.trim();
  const state = stateInput.value.trim();
  const district = districtInput.value.trim();
  const city = cityInput.value.trim();
  const limit = Number(limitInput.value);

  if (![country, state, district, city].some(Boolean)) {
    setMessage("Please enter at least one location field before searching.", "error");
    saveState();
    return;
  }

  searchButton.disabled = true;
  uploadButton.disabled = true;
  setMessage("Searching public business details. This can take a little time for website checks.");
  saveState();

  try {
    const response = await fetch("/api/search", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ country, state, district, city, limit }),
    });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.error || "Search failed.");
    }

    currentLocationContext = {
      search_location_parts: payload.location_parts || {},
      search_display_location: payload.location || "",
    };
    currentLeads = (payload.results || []).map((lead) => ({
      ...lead,
      ...currentLocationContext,
    }));
    currentSummary = `${payload.count} leads found for ${payload.location}. Details file updated at ${payload.details_file}.`;
    uploadButton.disabled = currentLeads.length === 0;
    applyLeadFilter();
    setMessage(`Search completed. ${payload.count} leads are ready.`, "success");
    saveState();
  } catch (error) {
    currentLeads = [];
    filteredLeads = [];
    currentLocationContext = null;
    currentSummary = "Search by location to generate public business leads.";
    renderRows([]);
    resultsMeta.textContent = currentSummary;
    setMessage(error.message, "error");
    saveState();
  } finally {
    searchButton.disabled = false;
  }
}

async function handleUpload() {
  if (!currentLeads.length) {
    setMessage("Search for leads before uploading.", "error");
    saveState();
    return;
  }

  uploadButton.disabled = true;
  setMessage("Uploading only new businesses into MongoDB.");
  saveState();

  try {
    const response = await fetch("/api/upload", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ leads: currentLeads }),
    });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.error || "Upload failed.");
    }

    setMessage(
      `Upload completed. Inserted ${payload.inserted} new leads, skipped ${payload.skipped_existing} existing leads in ${payload.database}.${payload.collection}.`,
      "success",
    );
    saveState();
  } catch (error) {
    setMessage(error.message, "error");
    saveState();
  } finally {
    uploadButton.disabled = currentLeads.length === 0;
  }
}

function handleSuggestionClick(event) {
  const target = event.target.closest(".suggestion-item");
  if (!target) {
    return;
  }
  leadSearchInput.value = target.dataset.value || "";
  hideSuggestions();
  applyLeadFilter();
  saveState();
}

function handleLeadSearchInput() {
  renderSuggestions(leadSearchInput.value);
  applyLeadFilter();
  saveState();
}

function handleDocumentClick(event) {
  if (
    event.target !== leadSearchInput &&
    !leadSuggestions.contains(event.target)
  ) {
    hideSuggestions();
  }
}

searchForm.addEventListener("submit", handleSearch);
uploadButton.addEventListener("click", handleUpload);
leadSearchInput.addEventListener("input", handleLeadSearchInput);
leadSearchInput.addEventListener("focus", () => renderSuggestions(leadSearchInput.value));
leadSuggestions.addEventListener("click", handleSuggestionClick);
document.addEventListener("click", handleDocumentClick);

restoreState();
if (!currentLeads.length) {
  resultsMeta.textContent = "Search by location to generate public business leads.";
}
