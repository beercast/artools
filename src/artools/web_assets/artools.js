(() => {
  "use strict";

  const simbadCache = new Map();
  let simbadSearchTimer = null;
  let simbadAbortController = null;

  function status(message, kind) {
    const node = document.getElementById("generation-status");
    if (!node) return;
    node.textContent = message;
    node.className = "generation-status" + (kind ? " " + kind : "");
  }

  function sourceStatus(message, kind) {
    const node = document.getElementById("simbad-source-status");
    if (!node) return;
    node.textContent = message || "";
    node.className = "source-message" + (kind ? " " + kind : "");
  }

  function filenameFromDisposition(value) {
    if (!value) return "trajectory.txt";
    const match = /filename="([^"]+)"/i.exec(value);
    return match ? match[1] : "trajectory.txt";
  }

  function automaticFilenameComponent(value) {
    return (value || "")
      .trim()
      .replace(/\s+/g, "_")
      .replace(/[^A-Za-z0-9_-]/g, "")
      .replace(/^[_-]+|[_-]+$/g, "");
  }

  function automaticFilenameEpoch() {
    const dateInput = document.getElementById("start-date");
    const timeInput = document.getElementById("start-time");
    if (!dateInput || !timeInput || !dateInput.value || !timeInput.value) return "";
    const date = dateInput.value.replace(/-/g, "");
    const parts = timeInput.value.split(":");
    if (parts.length < 2) return "";
    const hour = (parts[0] || "00").padStart(2, "0");
    const minute = (parts[1] || "00").padStart(2, "0");
    const second = ((parts[2] || "00").split(".")[0] || "00").padStart(2, "0");
    return `${date}T${hour}${minute}${second}Z`;
  }

  function automaticFilenameTarget() {
    const family = document.getElementById("target-family");
    if (!family) return "";

    if (family.value === "astronomical") {
      const input = document.getElementById("simbad-source-input");
      return input ? input.value.trim() : "";
    }
    if (family.value === "solar-system") {
      const select = document.querySelector('[name="body"]');
      return select ? select.value.trim() : "";
    }
    if (family.value === "satellite") {
      const source = document.getElementById("tle-source");
      if (source && source.value === "paste") {
        const textarea = document.getElementById("tle-text");
        if (!textarea) return "";
        const firstLine = textarea.value.split(/\r?\n/).find((line) => line.trim());
        return firstLine ? firstLine.trim() : "";
      }
      const input = document.getElementById("satellite-name-input");
      return input ? input.value.trim() : "";
    }
    return "";
  }

  function updateAutomaticOutputFilename() {
    const output = document.getElementById("output-name");
    if (!output || output.dataset.autoFilename !== "true") return;
    const target = automaticFilenameComponent(automaticFilenameTarget());
    const epoch = automaticFilenameEpoch();
    if (!target || !epoch) {
      output.value = "trajectory.txt";
      return;
    }
    output.value = `${target}_${epoch}.txt`;
  }

  function setCurrentUtc() {
    const dateInput = document.getElementById("start-date");
    const timeInput = document.getElementById("start-time");
    if (!dateInput || !timeInput) return;

    const now = new Date();
    const pad = (value) => String(value).padStart(2, "0");
    dateInput.value = `${now.getUTCFullYear()}-${pad(now.getUTCMonth() + 1)}-${pad(now.getUTCDate())}`;
    timeInput.value = `${pad(now.getUTCHours())}:${pad(now.getUTCMinutes())}:${pad(now.getUTCSeconds())}`;
    updateAutomaticOutputFilename();
  }

  async function jsonRequest(url, options = {}) {
    const response = await fetch(url, options);
    let payload = {};
    try {
      payload = await response.json();
    } catch (_) {}
    if (!response.ok) {
      throw new Error(payload.detail || "Request failed.");
    }
    return payload;
  }

  const siteState = {
    sites: [
      { source: "srt", name: "Sardinia Radio Telescope (SRT)" },
      { source: "custom", name: "Custom site..." },
    ],
  };

  function siteStatus(message, kind) {
    const node = document.getElementById("site-status");
    if (!node) return;
    node.textContent = message || "";
    node.className = "source-message" + (kind ? " " + kind : "");
  }

  function weatherStatus(message, kind) {
    const node = document.getElementById("weather-status");
    if (!node) return;
    node.textContent = message || "";
    node.className = "source-message" + (kind ? " " + kind : "");
  }

  function clearSiteSuggestions() {
    const menu = document.getElementById("site-suggestions");
    const input = document.getElementById("site-input");
    if (menu) {
      menu.replaceChildren();
      menu.hidden = true;
    }
    if (input) input.setAttribute("aria-expanded", "false");
  }

  function selectedSiteSource() {
    const source = document.getElementById("site-source");
    return source ? source.value : "";
  }

  function siteSourceLabel(site) {
    if (site.source === "saved") return "Saved";
    if (site.source === "astropy") return "Astropy catalog";
    if (site.source === "custom") return "Manual coordinates";
    return "Default";
  }

  function renderSiteSuggestions(query = "") {
    const menu = document.getElementById("site-suggestions");
    const input = document.getElementById("site-input");
    if (!menu || !input) return;
    const key = query.trim().toLowerCase();
    const matches = siteState.sites.filter(
      (site) => !key || site.name.toLowerCase().includes(key)
    );

    menu.replaceChildren();
    if (!matches.length) {
      const empty = document.createElement("div");
      empty.className = "autocomplete-empty";
      empty.textContent = "No observing sites match.";
      menu.appendChild(empty);
    } else {
      matches.forEach((site) => {
        const option = document.createElement("button");
        option.type = "button";
        option.className = "autocomplete-option";
        option.setAttribute("role", "option");

        const names = document.createElement("span");
        names.className = "autocomplete-names";
        const label = document.createElement("strong");
        label.textContent = site.name;
        const source = document.createElement("small");
        source.textContent = siteSourceLabel(site);
        names.append(label, source);
        option.appendChild(names);

        option.addEventListener("click", () => selectSite(site));
        menu.appendChild(option);
      });
    }
    menu.hidden = false;
    input.setAttribute("aria-expanded", "true");
  }

  function setCoordinateFields(site) {
    const customName = document.getElementById("site-custom-name");
    const latitude = document.getElementById("site-latitude");
    const longitude = document.getElementById("site-longitude");
    const height = document.getElementById("site-height");
    if (!customName || !latitude || !longitude || !height) return;

    if (site.source === "saved") {
      customName.value = site.name;
      latitude.value = site.latitude_deg;
      longitude.value = site.longitude_deg;
      height.value = site.height_m;
    } else if (site.source === "custom") {
      customName.value = "";
      latitude.value = "";
      longitude.value = "";
      height.value = "";
    }
  }

  function selectSite(site) {
    const input = document.getElementById("site-input");
    const source = document.getElementById("site-source");
    const name = document.getElementById("site-name");
    if (!input || !source || !name) return;

    input.value = site.name;
    input.dataset.selectedSite = site.name;
    source.value = site.source;
    name.value = site.source === "astropy" || site.source === "saved" ? site.name : "";
    setCoordinateFields(site);
    clearSiteSuggestions();
    updateSiteUi();
    siteStatus("", "");

    const refraction = document.getElementById("refraction-mode");
    const family = document.getElementById("target-family");
    if (
      refraction &&
      refraction.value === "atmospheric" &&
      family &&
      family.value !== "satellite" &&
      site.source !== "custom"
    ) {
      refreshWeather();
    }
  }

  function updateSiteUi() {
    const source = selectedSiteSource();
    const custom = document.getElementById("custom-site-fields");
    const customName = document.getElementById("site-custom-name");
    const latitude = document.getElementById("site-latitude");
    const longitude = document.getElementById("site-longitude");
    const height = document.getElementById("site-height");
    const save = document.getElementById("save-custom-site");
    const remove = document.getElementById("delete-saved-site");
    const footer = document.getElementById("observer-footer");
    const input = document.getElementById("site-input");
    const name = document.getElementById("site-name");
    const isCustom = source === "custom";
    const isSaved = source === "saved";
    const showCoordinates = isCustom || isSaved;

    if (custom) custom.hidden = !showCoordinates;
    if (customName) {
      customName.readOnly = isSaved;
      customName.required = false;
    }
    [latitude, longitude, height].forEach((field) => {
      if (!field) return;
      field.required = isCustom;
      field.readOnly = isSaved;
    });
    if (save) save.hidden = !isCustom;
    if (remove) remove.hidden = !isSaved;

    if (isCustom && name && customName) name.value = customName.value.trim();
    if (footer) {
      const customLabel = customName && customName.value.trim() ? customName.value.trim() : "Custom site";
      const label = isCustom ? customLabel : (input && input.value ? input.value : "Observing site");
      footer.textContent = `Observer: ${label}`;
    }
  }

  async function loadSites() {
    try {
      const payload = await jsonRequest("/api/sites");
      if (Array.isArray(payload.sites) && payload.sites.length) {
        siteState.sites = payload.sites;
      }
      if (payload.catalog_available === false && payload.detail) {
        siteStatus(`${payload.detail}. SRT, saved sites, and Custom site remain available.`, "error");
      }
    } catch (error) {
      siteStatus(
        error instanceof Error ? error.message : "Could not load the observing-site catalog.",
        "error"
      );
    }
  }

  function customSitePayload() {
    const name = document.getElementById("site-custom-name");
    const latitude = document.getElementById("site-latitude");
    const longitude = document.getElementById("site-longitude");
    const height = document.getElementById("site-height");
    if (!name || !latitude || !longitude || !height) throw new Error("Custom site fields are unavailable.");
    if (!name.value.trim()) throw new Error("Enter a site name before saving.");
    if (!latitude.value || !longitude.value || !height.value) {
      throw new Error("Enter latitude, longitude, and altitude before saving.");
    }
    return {
      name: name.value.trim(),
      latitude_deg: Number(latitude.value),
      longitude_deg: Number(longitude.value),
      height_m: Number(height.value),
    };
  }

  async function saveCustomSite() {
    const button = document.getElementById("save-custom-site");
    try {
      const payload = customSitePayload();
      if (button) button.disabled = true;
      const response = await jsonRequest("/api/sites/custom", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      await loadSites();
      selectSite(response.site);
      siteStatus(`Saved observing site: ${response.site.name}.`, "success");
    } catch (error) {
      siteStatus(error instanceof Error ? error.message : "Could not save observing site.", "error");
    } finally {
      if (button) button.disabled = false;
    }
  }

  async function deleteSavedSite() {
    const name = document.getElementById("site-name");
    if (!name || !name.value) return;
    if (!window.confirm(`Delete saved observing site "${name.value}"?`)) return;
    const button = document.getElementById("delete-saved-site");
    try {
      if (button) button.disabled = true;
      await jsonRequest(`/api/sites/custom?name=${encodeURIComponent(name.value)}`, { method: "DELETE" });
      await loadSites();
      const srt = siteState.sites.find((site) => site.source === "srt");
      if (srt) selectSite(srt);
      siteStatus("Saved observing site deleted.", "success");
    } catch (error) {
      siteStatus(error instanceof Error ? error.message : "Could not delete observing site.", "error");
    } finally {
      if (button) button.disabled = false;
    }
  }

  function weatherStartTime() {
    const dateInput = document.getElementById("start-date");
    const timeInput = document.getElementById("start-time");
    if (!dateInput || !timeInput || !dateInput.value || !timeInput.value) return "";
    return `${dateInput.value}T${timeInput.value}Z`;
  }

  function weatherQuery() {
    const source = document.getElementById("site-source");
    const name = document.getElementById("site-name");
    if (!source || !source.value) throw new Error("Choose an observing site first.");
    const params = new URLSearchParams({
      site_source: source.value,
      site_name: name ? name.value : "",
      at: weatherStartTime(),
    });
    if (source.value === "custom") {
      const latitude = document.getElementById("site-latitude");
      const longitude = document.getElementById("site-longitude");
      const height = document.getElementById("site-height");
      if (!latitude || !longitude || !height || !latitude.value || !longitude.value || !height.value) {
        throw new Error("Enter custom latitude, longitude, and altitude before loading weather.");
      }
      params.set("latitude", latitude.value);
      params.set("longitude", longitude.value);
      params.set("height", height.value);
    }
    if (!params.get("at")) throw new Error("Choose a trajectory start time first.");
    return params;
  }

  async function refreshWeather() {
    const button = document.getElementById("refresh-weather");
    const family = document.getElementById("target-family");
    if (family && family.value === "satellite") return;

    try {
      const params = weatherQuery();
      if (button) button.disabled = true;
      weatherStatus("Loading Open-Meteo weather data...", "");
      const payload = await jsonRequest(`/api/weather?${params.toString()}`);
      const pressure = document.getElementById("pressure-hpa");
      const temperature = document.getElementById("temperature-c");
      const humidity = document.getElementById("relative-humidity");
      const validity = document.getElementById("weather-validity");
      if (pressure) pressure.value = Number(payload.pressure_hpa).toFixed(1);
      if (temperature) temperature.value = Number(payload.temperature_c).toFixed(1);
      if (humidity) humidity.value = Number(payload.relative_humidity_percent).toFixed(1);
      if (validity) {
        const validAt = String(payload.valid_at || "").replace("T", " ").replace("Z", " UTC");
        validity.textContent = `${payload.source || "Open-Meteo"} · valid ${validAt}`;
      }
      weatherStatus("Weather loaded. Values remain editable.", "success");
    } catch (error) {
      weatherStatus(
        error instanceof Error ? error.message : "Could not load weather data.",
        "error"
      );
    } finally {
      if (button) button.disabled = false;
    }
  }

  function updateRefractionUi(loadWeather = false) {
    const refraction = document.getElementById("refraction-mode");
    const controls = document.getElementById("atmospheric-controls");
    const family = document.getElementById("target-family");
    const refresh = document.getElementById("refresh-weather");
    const note = document.getElementById("satellite-refraction-note");
    const prefillHint = document.getElementById("weather-prefill-hint");
    const weatherStatusNode = document.getElementById("weather-status");
    const validity = document.getElementById("weather-validity");
    if (!refraction || !controls || !family) return;

    const enabled = refraction.value === "atmospheric";
    const satellite = family.value === "satellite";
    controls.hidden = !enabled;
    document.querySelectorAll(".weather-value-field").forEach((field) => {
      field.hidden = satellite;
    });
    document.querySelectorAll(".weather-input").forEach((field) => {
      field.required = enabled && !satellite;
    });
    if (refresh) refresh.hidden = satellite;
    if (prefillHint) prefillHint.hidden = satellite;
    if (weatherStatusNode) weatherStatusNode.hidden = satellite;
    if (note) note.hidden = !satellite;
    if (satellite && validity) validity.textContent = "Legacy Pycraf atmospheric profile";
    if (!satellite && validity && validity.textContent === "Legacy Pycraf atmospheric profile") {
      validity.textContent = "";
    }
    if (enabled && !satellite && loadWeather && selectedSiteSource() !== "custom") {
      refreshWeather();
    }
  }

  function initEnvironmentControls() {
    const siteInput = document.getElementById("site-input");
    const siteToggle = document.getElementById("site-menu-toggle");
    const customName = document.getElementById("site-custom-name");
    const saveSite = document.getElementById("save-custom-site");
    const deleteSite = document.getElementById("delete-saved-site");
    const refraction = document.getElementById("refraction-mode");
    const refresh = document.getElementById("refresh-weather");
    if (!siteInput || siteInput.dataset.siteReady === "true") return;

    siteInput.dataset.siteReady = "true";
    siteInput.addEventListener("input", () => {
      const source = document.getElementById("site-source");
      const name = document.getElementById("site-name");
      if (source) source.value = "";
      if (name) name.value = "";
      delete siteInput.dataset.selectedSite;
      updateSiteUi();
      renderSiteSuggestions(siteInput.value);
    });
    siteInput.addEventListener("focus", () => renderSiteSuggestions(""));
    if (siteToggle) {
      siteToggle.addEventListener("click", () => {
        const menu = document.getElementById("site-suggestions");
        if (menu && !menu.hidden) clearSiteSuggestions();
        else renderSiteSuggestions("");
      });
    }
    if (customName) customName.addEventListener("input", updateSiteUi);
    if (saveSite) saveSite.addEventListener("click", saveCustomSite);
    if (deleteSite) deleteSite.addEventListener("click", deleteSavedSite);
    if (refraction) {
      refraction.addEventListener("change", () => updateRefractionUi(true));
    }
    if (refresh) refresh.addEventListener("click", refreshWeather);

    updateSiteUi();
    updateRefractionUi(false);
    loadSites();
  }

  async function submitTrajectory(form) {
    const button = document.getElementById("generate-button");
    button.disabled = true;
    button.classList.add("is-generating");
    status("Generating trajectory locally...", "");

    try {
      const response = await fetch(form.action, {
        method: "POST",
        body: new FormData(form),
      });
      if (!response.ok) {
        let message = "Generation failed.";
        try {
          const payload = await response.json();
          if (payload.detail) message = payload.detail;
        } catch (_) {}
        throw new Error(message);
      }

      const blob = await response.blob();
      const filename = filenameFromDisposition(response.headers.get("Content-Disposition"));
      const pointCount = response.headers.get("X-ARTools-Point-Count");
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
      status(`Generated ${pointCount || ""} trajectory points. Download started.`, "success");
    } catch (error) {
      status(error instanceof Error ? error.message : "Generation failed.", "error");
    } finally {
      button.disabled = false;
      button.classList.remove("is-generating");
    }
  }

  function favoriteDisplayName(name) {
    return (name || "").trim().replace(/^NAME\s+/i, "");
  }

  function favoriteKey(name) {
    return favoriteDisplayName(name).toLowerCase();
  }

  function setCanonicalSource(name) {
    const input = document.getElementById("simbad-source-input");
    const hidden = document.getElementById("simbad-source-canonical");
    const value = (name || "").trim();
    if (input) {
      if (value) input.dataset.mainId = value;
      else delete input.dataset.mainId;
    }
    if (hidden) hidden.value = value;
  }

  function favoriteValues() {
    const select = document.getElementById("simbad-favorites-select");
    if (!select) return [];
    return Array.from(select.options)
      .map((option) => option.value)
      .filter(Boolean);
  }

  function isFavorite(name) {
    const key = favoriteKey(name);
    return Boolean(key) && favoriteValues().some((item) => favoriteKey(item) === key);
  }

  function populateFavorites(favorites) {
    const select = document.getElementById("simbad-favorites-select");
    if (!select) return;
    const previous = select.value;
    select.replaceChildren();

    const placeholder = document.createElement("option");
    placeholder.value = "";
    placeholder.textContent = favorites.length ? "Select favorite" : "No favorites saved";
    select.appendChild(placeholder);

    favorites.forEach((name) => {
      const option = document.createElement("option");
      option.value = name;
      option.dataset.displayName = favoriteDisplayName(name);
      option.textContent = option.dataset.displayName;
      select.appendChild(option);
    });

    if (favorites.includes(previous)) select.value = previous;
    updateFavoriteToggle();
  }

  function updateFavoriteToggle() {
    const input = document.getElementById("simbad-source-input");
    const button = document.getElementById("simbad-favorite-toggle");
    if (!input || !button) return;

    const typed = input.value.trim();
    const canonical = input.dataset.mainId || typed;
    const favorite = isFavorite(canonical);
    button.disabled = !typed;
    button.classList.toggle("is-favorite", favorite);
    button.dataset.favoriteName = favorite ? canonical : "";
    const icon = button.querySelector("span");
    if (icon) icon.textContent = favorite ? "★" : "☆";
    const label = favorite ? "Remove source from favorites" : "Add source to favorites";
    button.setAttribute("aria-label", label);
    button.title = label;
  }

  function clearSuggestions() {
    const menu = document.getElementById("simbad-suggestions");
    const input = document.getElementById("simbad-source-input");
    if (!menu) return;
    menu.replaceChildren();
    menu.hidden = true;
    if (input) input.setAttribute("aria-expanded", "false");
  }

  function renderSuggestions(suggestions, limitReached = false, limit = 20) {
    const menu = document.getElementById("simbad-suggestions");
    const input = document.getElementById("simbad-source-input");
    if (!menu || !input) return;
    menu.replaceChildren();

    if (limitReached) {
      const note = document.createElement("div");
      note.className = "autocomplete-limit-note";
      note.textContent = `Showing the first ${limit} matches. Type more characters to refine the search.`;
      menu.appendChild(note);
    }

    if (!suggestions.length) {
      const empty = document.createElement("div");
      empty.className = "autocomplete-empty";
      empty.textContent = "No SIMBAD matches.";
      menu.appendChild(empty);
    } else {
      suggestions.forEach((suggestion) => {
        const option = document.createElement("button");
        option.type = "button";
        option.className = "autocomplete-option";
        option.setAttribute("role", "option");

        const names = document.createElement("span");
        names.className = "autocomplete-names";
        const matched = document.createElement("strong");
        matched.textContent = suggestion.name;
        names.appendChild(matched);
        if (suggestion.main_id && suggestion.main_id.toLowerCase() !== suggestion.name.toLowerCase()) {
          const main = document.createElement("small");
          main.textContent = suggestion.main_id;
          names.appendChild(main);
        }
        option.appendChild(names);

        if (isFavorite(suggestion.main_id) || suggestion.favorite) {
          const marker = document.createElement("span");
          marker.className = "favorite-marker";
          marker.textContent = "★";
          marker.title = "Already in favorites";
          marker.setAttribute("aria-label", "Already in favorites");
          option.appendChild(marker);
        }

        option.addEventListener("click", () => {
          input.value = suggestion.name;
          setCanonicalSource(suggestion.main_id || suggestion.name);
          sourceStatus("", "");
          clearSuggestions();
          updateFavoriteToggle();
          updateAutomaticOutputFilename();
        });
        menu.appendChild(option);
      });
    }

    menu.hidden = false;
    input.setAttribute("aria-expanded", "true");
  }

  async function searchSimbad(query) {
    const key = query.trim().toLowerCase();
    if (simbadCache.has(key)) {
      const cached = simbadCache.get(key);
      renderSuggestions(cached.suggestions, cached.limitReached, cached.limit);
      return;
    }

    if (simbadAbortController) simbadAbortController.abort();
    simbadAbortController = new AbortController();
    try {
      const payload = await jsonRequest(`/api/simbad/suggestions?q=${encodeURIComponent(query)}`, {
        signal: simbadAbortController.signal,
      });
      const result = {
        suggestions: Array.isArray(payload.suggestions) ? payload.suggestions : [],
        limitReached: Boolean(payload.limit_reached),
        limit: Number.isInteger(payload.limit) ? payload.limit : 20,
      };
      simbadCache.set(key, result);
      renderSuggestions(result.suggestions, result.limitReached, result.limit);
      sourceStatus("", "");
    } catch (error) {
      if (error && error.name === "AbortError") return;
      clearSuggestions();
      sourceStatus(error instanceof Error ? error.message : "SIMBAD search failed.", "error");
    }
  }

  function scheduleSimbadSearch() {
    const input = document.getElementById("simbad-source-input");
    if (!input) return;
    const query = input.value.trim();
    setCanonicalSource("");
    updateFavoriteToggle();
    sourceStatus("", "");
    if (simbadSearchTimer) window.clearTimeout(simbadSearchTimer);
    if (query.length < 2) {
      clearSuggestions();
      return;
    }
    simbadSearchTimer = window.setTimeout(() => searchSimbad(query), 350);
  }

  async function loadFavorites() {
    if (!document.getElementById("simbad-favorites-select")) return;
    try {
      const payload = await jsonRequest("/api/simbad/favorites");
      populateFavorites(Array.isArray(payload.favorites) ? payload.favorites : []);
      sourceStatus("", "");
    } catch (error) {
      sourceStatus(error instanceof Error ? error.message : "Could not load favorites.", "error");
    }
  }

  async function toggleFavorite() {
    const input = document.getElementById("simbad-source-input");
    const button = document.getElementById("simbad-favorite-toggle");
    if (!input || !button || !input.value.trim()) return;

    button.disabled = true;
    const favoriteName = button.dataset.favoriteName;
    try {
      let payload;
      if (favoriteName) {
        payload = await jsonRequest(`/api/simbad/favorites?name=${encodeURIComponent(favoriteName)}`, {
          method: "DELETE",
        });
      } else {
        payload = await jsonRequest("/api/simbad/favorites", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ name: input.value.trim() }),
        });
        if (payload.favorite) setCanonicalSource(payload.favorite);
      }
      populateFavorites(Array.isArray(payload.favorites) ? payload.favorites : []);
      sourceStatus(favoriteName ? "Removed from favorites." : "Added to favorites.", "success");
      simbadCache.clear();
    } catch (error) {
      sourceStatus(error instanceof Error ? error.message : "Could not update favorites.", "error");
    } finally {
      updateFavoriteToggle();
    }
  }

  function initAstronomicalSourceControls() {
    const input = document.getElementById("simbad-source-input");
    const toggle = document.getElementById("simbad-favorite-toggle");
    const favorites = document.getElementById("simbad-favorites-select");
    if (!input || !toggle || !favorites || input.dataset.autocompleteReady === "true") return;

    input.dataset.autocompleteReady = "true";
    input.addEventListener("input", scheduleSimbadSearch);
    input.addEventListener("focus", () => {
      const query = input.value.trim();
      if (query.length >= 2) scheduleSimbadSearch();
    });
    toggle.addEventListener("click", toggleFavorite);
    favorites.addEventListener("change", () => {
      if (!favorites.value) return;
      const selected = favorites.options[favorites.selectedIndex];
      input.value = selected.dataset.displayName || favoriteDisplayName(favorites.value);
      setCanonicalSource(favorites.value);
      clearSuggestions();
      sourceStatus("", "");
      updateFavoriteToggle();
      updateAutomaticOutputFilename();
    });

    loadFavorites();
  }

  const satelliteState = {
    source: "download",
    download: { loaded: false, catalogId: "", filename: "", satellites: [] },
    upload: { loaded: false, catalogId: "", filename: "", satellites: [] },
    pasteText: "",
  };

  function satelliteStatus(id, message, kind) {
    const node = document.getElementById(id);
    if (!node) return;
    node.textContent = message || "";
    node.className = "source-message" + (kind ? " " + kind : "");
  }

  function clearSatelliteSuggestions() {
    const menu = document.getElementById("satellite-suggestions");
    const input = document.getElementById("satellite-name-input");
    if (menu) {
      menu.replaceChildren();
      menu.hidden = true;
    }
    if (input) input.setAttribute("aria-expanded", "false");
  }

  function activeSatelliteCatalog() {
    if (satelliteState.source === "download") return satelliteState.download;
    if (satelliteState.source === "upload") return satelliteState.upload;
    return null;
  }

  function renderSatelliteSuggestions(query = "") {
    const menu = document.getElementById("satellite-suggestions");
    const input = document.getElementById("satellite-name-input");
    const catalog = activeSatelliteCatalog();
    if (!menu || !input || !catalog || !catalog.loaded) return;

    const key = query.trim().toLowerCase();
    const matches = catalog.satellites
      .filter((name) => !key || name.toLowerCase().includes(key));

    menu.replaceChildren();
    if (!matches.length) {
      const empty = document.createElement("div");
      empty.className = "autocomplete-empty";
      empty.textContent = "No satellites match.";
      menu.appendChild(empty);
    } else {
      matches.forEach((name) => {
        const option = document.createElement("button");
        option.type = "button";
        option.className = "autocomplete-option";
        option.setAttribute("role", "option");

        const names = document.createElement("span");
        names.className = "autocomplete-names";
        const label = document.createElement("strong");
        label.textContent = name;
        names.appendChild(label);
        option.appendChild(names);

        option.addEventListener("click", () => {
          input.value = name;
          input.dataset.selectedName = name;
          clearSatelliteSuggestions();
          updateAutomaticOutputFilename();
        });
        menu.appendChild(option);
      });
    }

    menu.hidden = false;
    input.setAttribute("aria-expanded", "true");
  }

  function setSatelliteCatalog(kind, payload) {
    const catalog = satelliteState[kind];
    catalog.loaded = Boolean(payload && payload.available);
    catalog.catalogId = payload && payload.catalog_id ? payload.catalog_id : "";
    catalog.filename = payload && payload.filename ? payload.filename : "";
    catalog.satellites = payload && Array.isArray(payload.satellites)
      ? payload.satellites.slice().sort((left, right) => left.localeCompare(right))
      : [];
    updateSatelliteSourceUi();
  }

  function updateSatelliteSourceUi() {
    const source = document.getElementById("tle-source");
    const downloadPanel = document.getElementById("tle-download-panel");
    const uploadPanel = document.getElementById("tle-upload-panel");
    const pastePanel = document.getElementById("tle-paste-panel");
    const selector = document.getElementById("satellite-catalog-selection");
    const input = document.getElementById("satellite-name-input");
    const catalogId = document.getElementById("tle-catalog-id");
    const paste = document.getElementById("tle-text");
    const hint = document.getElementById("satellite-catalog-hint");
    const downloadButton = document.getElementById("tle-download-button");
    const downloadCheck = document.getElementById("tle-download-check");
    const uploadCheck = document.getElementById("tle-upload-check");
    if (!source) return;

    source.value = satelliteState.source;
    if (downloadPanel) downloadPanel.hidden = satelliteState.source !== "download";
    if (uploadPanel) uploadPanel.hidden = satelliteState.source !== "upload";
    if (pastePanel) pastePanel.hidden = satelliteState.source !== "paste";

    if (paste) {
      paste.required = satelliteState.source === "paste";
      if (document.activeElement !== paste) paste.value = satelliteState.pasteText;
    }

    const catalog = activeSatelliteCatalog();
    const catalogReady = Boolean(catalog && catalog.loaded);
    if (selector) selector.hidden = !catalogReady;
    if (input) {
      input.required = catalogReady;
      input.disabled = !catalogReady;
      if (!catalogReady) input.value = "";
    }
    if (catalogId) catalogId.value = catalogReady ? catalog.catalogId : "";
    if (hint) {
      hint.textContent = catalogReady
        ? `${catalog.satellites.length} satellites available from ${catalog.filename}. Type to filter the list.`
        : "";
    }
    if (downloadButton) downloadButton.textContent = satelliteState.download.loaded ? "Refresh" : "Download";
    if (downloadCheck) downloadCheck.hidden = !satelliteState.download.loaded;
    if (uploadCheck) uploadCheck.hidden = !satelliteState.upload.loaded;
    clearSatelliteSuggestions();
  }

  async function loadDownloadedCatalogStatus() {
    try {
      const payload = await jsonRequest("/api/tle/downloaded");
      setSatelliteCatalog("download", payload);
      if (payload.available) {
        satelliteStatus(
          "tle-download-status",
          `Saved catalog ready (${payload.count} satellites).`,
          "success"
        );
      } else {
        satelliteStatus("tle-download-status", "No saved catalog yet.", "");
      }
    } catch (error) {
      satelliteStatus(
        "tle-download-status",
        error instanceof Error ? error.message : "Could not read the saved TLE catalog.",
        "error"
      );
    }
  }

  async function downloadSatelliteCatalog() {
    const button = document.getElementById("tle-download-button");
    if (!button) return;
    const oldLabel = button.textContent;
    button.disabled = true;
    button.textContent = satelliteState.download.loaded ? "Refreshing..." : "Downloading...";
    satelliteStatus("tle-download-status", "Downloading CelesTrak GEO catalog...", "");
    try {
      const payload = await jsonRequest("/api/tle/download", { method: "POST" });
      setSatelliteCatalog("download", payload);
      satelliteStatus(
        "tle-download-status",
        `Catalog saved (${payload.count} satellites).`,
        "success"
      );
    } catch (error) {
      button.textContent = oldLabel;
      satelliteStatus(
        "tle-download-status",
        error instanceof Error ? error.message : "TLE download failed.",
        "error"
      );
    } finally {
      button.disabled = false;
      if (satelliteState.download.loaded) button.textContent = "Refresh";
    }
  }

  async function uploadSatelliteCatalog(file) {
    if (!file) return;
    const button = document.getElementById("tle-upload-button");
    if (button) {
      button.disabled = true;
      button.textContent = "Loading...";
    }
    satelliteStatus("tle-upload-status", `Reading ${file.name}...`, "");
    const formData = new FormData();
    formData.append("catalog_file", file);
    try {
      const payload = await jsonRequest("/api/tle/upload", { method: "POST", body: formData });
      setSatelliteCatalog("upload", payload);
      satelliteStatus(
        "tle-upload-status",
        `Loaded ${payload.count} satellites. Copy saved as ${payload.filename}.`,
        "success"
      );
    } catch (error) {
      satelliteState.upload = { loaded: false, catalogId: "", filename: "", satellites: [] };
      updateSatelliteSourceUi();
      satelliteStatus(
        "tle-upload-status",
        error instanceof Error ? error.message : "Could not load TLE catalog.",
        "error"
      );
    } finally {
      if (button) {
        button.disabled = false;
        button.textContent = "Upload file";
      }
    }
  }

  async function openTleFolder() {
    try {
      await jsonRequest("/api/tle/open-folder", { method: "POST" });
      satelliteStatus("tle-upload-status", "Opened the ARTools TLE folder.", "success");
    } catch (error) {
      satelliteStatus(
        "tle-upload-status",
        error instanceof Error ? error.message : "Could not open the TLE folder.",
        "error"
      );
    }
  }

  function initSatelliteControls() {
    const source = document.getElementById("tle-source");
    const downloadButton = document.getElementById("tle-download-button");
    const uploadButton = document.getElementById("tle-upload-button");
    const openFolderButton = document.getElementById("tle-open-folder-button");
    const fileInput = document.getElementById("tle-catalog-file");
    const satelliteInput = document.getElementById("satellite-name-input");
    const paste = document.getElementById("tle-text");
    if (!source || source.dataset.satelliteReady === "true") return;

    source.dataset.satelliteReady = "true";
    source.value = satelliteState.source;
    source.addEventListener("change", () => {
      satelliteState.source = source.value;
      updateSatelliteSourceUi();
      if (satelliteState.source === "download" && !satelliteState.download.loaded) {
        loadDownloadedCatalogStatus();
      }
    });

    if (downloadButton) downloadButton.addEventListener("click", downloadSatelliteCatalog);
    if (uploadButton && fileInput) uploadButton.addEventListener("click", () => fileInput.click());
    if (fileInput) {
      fileInput.addEventListener("change", () => {
        const file = fileInput.files && fileInput.files[0];
        if (file) uploadSatelliteCatalog(file);
        fileInput.value = "";
      });
    }
    if (openFolderButton) openFolderButton.addEventListener("click", openTleFolder);
    if (satelliteInput) {
      satelliteInput.addEventListener("input", () => {
        delete satelliteInput.dataset.selectedName;
        renderSatelliteSuggestions(satelliteInput.value);
      });
      satelliteInput.addEventListener("focus", () => renderSatelliteSuggestions(satelliteInput.value));
    }
    if (paste) {
      paste.addEventListener("input", () => { satelliteState.pasteText = paste.value; });
    }

    updateSatelliteSourceUi();
    if (satelliteState.source === "download" && !satelliteState.download.loaded) {
      loadDownloadedCatalogStatus();
    }
  }

  async function dynamicFields() {
    const family = document.getElementById("target-family");
    const mode = document.getElementById("trajectory-mode");
    const target = document.getElementById("dynamic-fields");
    if (!family || !mode || !target) return;

    async function refresh() {
      const params = new URLSearchParams({ target_family: family.value, mode: mode.value });
      try {
        const response = await fetch(`/ui/fields?${params}`);
        if (response.ok) {
          target.innerHTML = await response.text();
          initAstronomicalSourceControls();
          initSatelliteControls();
          updateRefractionUi(false);
          updateAutomaticOutputFilename();
        }
      } catch (_) {
        // The initial server-rendered fields remain usable if the request fails.
      }
    }
    family.addEventListener("change", refresh);
    mode.addEventListener("change", refresh);
  }

  document.addEventListener("click", (event) => {
    const siteField = document.querySelector(".site-search-field");
    if (siteField && !siteField.contains(event.target)) clearSiteSuggestions();
    const sourceField = document.querySelector(".source-search-field");
    if (sourceField && !sourceField.contains(event.target)) clearSuggestions();
    const satelliteField = document.querySelector(".satellite-catalog-selection");
    if (satelliteField && !satelliteField.contains(event.target)) clearSatelliteSuggestions();
  });

  document.addEventListener("DOMContentLoaded", () => {
    const form = document.querySelector("[data-generate-form]");
    if (form) {
      form.addEventListener("submit", (event) => {
        event.preventDefault();
        submitTrajectory(form);
      });
      form.addEventListener("input", (event) => {
        if (event.target && event.target.id === "output-name") {
          event.target.dataset.autoFilename = "false";
          return;
        }
        updateAutomaticOutputFilename();
      });
      form.addEventListener("change", (event) => {
        if (event.target && event.target.id !== "output-name") {
          updateAutomaticOutputFilename();
        }
      });
    }
    const currentUtcButton = document.getElementById("use-current-utc");
    if (currentUtcButton) currentUtcButton.addEventListener("click", setCurrentUtc);
    initEnvironmentControls();
    dynamicFields();
    initAstronomicalSourceControls();
    initSatelliteControls();
  });
})();
