"""HTML rendering helpers for the local ARTools web interface."""

from __future__ import annotations

from datetime import datetime, timezone
from html import escape

from .solar_system import SolarSystemBody


def render_index() -> str:
    """Render the complete first-load page."""
    now = datetime.now(timezone.utc).replace(microsecond=0)
    start_date = now.date().isoformat()
    start_time = now.time().isoformat()
    return f'''<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>ARTools</title>
  <link rel="stylesheet" href="/static/artools.css">
  <script defer src="/static/artools.js"></script>
</head>
<body>
  <main class="shell">
    <header class="hero">
      <div>
        <p class="eyebrow">SRT Auxiliary Reference Telescope tools</p>
        <h1>ARTools</h1>
        <p class="subtitle">Trajectory generator</p>
      </div>
      <div class="status-chip"><span class="status-dot"></span>Local server</div>
    </header>

    <section class="panel">
      <form id="trajectory-form" action="/generate" method="post" enctype="multipart/form-data" data-generate-form>
        <div class="section-heading">
          <div><span class="step">01</span><h2>Trajectory</h2></div>
          <p>Choose the telescope, target family, and trajectory mode.</p>
        </div>

        <div class="grid three">
          <label>
            <span>Telescope</span>
            <select name="controlled_system" id="controlled-system">
              <option value="auxiliary_telescope">Auxiliary Telescope</option>
            </select>
          </label>
          <label>
            <span>Target family</span>
            <select name="target_family" id="target-family">
              <option value="astronomical">Astronomical source</option>
              <option value="solar-system">Solar System body</option>
              <option value="satellite">Artificial satellite</option>
            </select>
          </label>
          <label>
            <span>Mode</span>
            <select name="mode" id="trajectory-mode">
              <option value="track">Tracking</option>
              <option value="cross-scan">Cross scan</option>
              <option value="map">Raster map</option>
            </select>
          </label>
        </div>

        <div class="section-heading compact">
          <div><span class="step">02</span><h2>Parameters</h2></div>
          <p>Start time is always interpreted explicitly as UTC.</p>
        </div>

        <div class="parameter-grid">
          <fieldset class="start-time-fieldset">
            <legend>Start time <small>UTC</small></legend>
            <div class="start-time-controls">
              <label>
                <span>Date</span>
                <input name="start_date" id="start-date" type="date" required value="{start_date}">
              </label>
              <label>
                <span>Time</span>
                <input name="start_time" id="start-time" type="time" required step="1" value="{start_time}">
              </label>
              <button class="secondary utc-now-button" type="button" id="use-current-utc">Use current UTC time</button>
            </div>
          </fieldset>
          <div class="sampling-grid">
            <label>
              <span>Sample interval <small>s</small></span>
              <input name="dt" type="number" required min="0.000001" step="any" value="1">
            </label>
            <label>
              <span>Requested points</span>
              <input name="points" type="number" required min="1" step="1" value="5">
            </label>
          </div>
        </div>

        <div class="environment-grid">
          <div class="site-search-field">
            <span class="field-label">Observing site</span>
            <div class="site-autocomplete">
              <div class="site-input-row">
                <input id="site-input" type="text" value="Sardinia Radio Telescope (SRT)"
                  autocomplete="off" role="combobox" aria-autocomplete="list"
                  aria-controls="site-suggestions" aria-haspopup="listbox" aria-expanded="false">
                <button class="site-menu-toggle" type="button" id="site-menu-toggle"
                  aria-label="Show observing sites" aria-controls="site-suggestions">&#9662;</button>
              </div>
              <input name="site_source" id="site-source" type="hidden" value="srt">
              <input name="site_name" id="site-name" type="hidden" value="">
              <div id="site-suggestions" class="autocomplete-menu" role="listbox" hidden></div>
            </div>
            <div id="site-status" class="source-message" role="status" aria-live="polite"></div>
          </div>

          <label>
            <span>Refraction</span>
            <select name="refraction_mode" id="refraction-mode">
              <option value="none" selected>No refraction</option>
              <option value="atmospheric">Atmospheric refraction</option>
            </select>
          </label>
        </div>

        <div id="custom-site-fields" class="custom-site-fields" hidden>
          <div class="grid four custom-site-grid">
            <label><span>Site name</span>
              <input id="site-custom-name" type="text" autocomplete="off">
            </label>
            <label><span>Latitude <small>deg</small></span>
              <input name="site_latitude_deg" id="site-latitude" type="number" min="-90" max="90" step="any">
            </label>
            <label><span>Longitude <small>deg</small></span>
              <input name="site_longitude_deg" id="site-longitude" type="number" min="-180" max="180" step="any">
            </label>
            <label><span>Altitude <small>m</small></span>
              <input name="site_height_m" id="site-height" type="number" step="any">
            </label>
          </div>
          <div class="site-action-row">
            <button class="secondary" type="button" id="save-custom-site">Save site</button>
            <button class="secondary danger-button" type="button" id="delete-saved-site" hidden>Delete saved site</button>
          </div>
        </div>

        <div id="atmospheric-controls" class="atmospheric-controls" hidden>
          <div class="atmospheric-heading">
            <div>
              <strong>Atmospheric parameters</strong>
              <span id="weather-validity" class="atmospheric-meta"></span>
            </div>
            <button class="secondary" type="button" id="refresh-weather">Refresh weather</button>
          </div>
          <p id="weather-prefill-hint" class="hint">Weather values can be loaded from Open-Meteo for the selected site and trajectory start time, then edited manually.</p>
          <div class="grid four detail-grid atmospheric-grid">
            <label class="weather-value-field"><span>Pressure <small>hPa</small></span>
              <input name="pressure_hpa" id="pressure-hpa" class="weather-input" type="number" min="0" step="any">
            </label>
            <label class="weather-value-field"><span>Temperature <small>deg C</small></span>
              <input name="temperature_c" id="temperature-c" class="weather-input" type="number" step="any">
            </label>
            <label class="weather-value-field"><span>Relative humidity <small>%</small></span>
              <input name="relative_humidity" id="relative-humidity" class="weather-input" type="number" min="0" max="100" step="any">
            </label>
            <label><span>Observing frequency <small>GHz</small></span>
              <input name="frequency_ghz" id="frequency-ghz" type="number" min="0.000001" step="any" value="22">
            </label>
          </div>
          <p id="satellite-refraction-note" class="hint" hidden>Satellite refraction uses the legacy Pycraf mid-latitude summer atmospheric profile. The selected site altitude and observing frequency are used; the weather values are not.</p>
          <div id="weather-status" class="source-message" role="status" aria-live="polite"></div>
        </div>

        <div id="dynamic-fields">
          {render_dynamic_fields("astronomical", "track")}
        </div>

        <div class="section-heading compact">
          <div><span class="step">03</span><h2>Output</h2></div>
          <p>The trajectory is generated locally and downloaded by the browser.</p>
        </div>
        <div class="grid output-grid">
          <label>
            <span>Download filename</span>
            <input name="output_name" id="output-name" type="text" value="trajectory.txt" required autocomplete="off" data-auto-filename="true">
          </label>
          <div class="action-wrap">
            <button class="primary" type="submit" id="generate-button">
              <span>Generate trajectory</span>
              <span class="spinner" aria-hidden="true"></span>
            </button>
          </div>
        </div>
        <div id="generation-status" class="generation-status" role="status" aria-live="polite">
          Ready.
        </div>
      </form>
    </section>

    <footer>
      <span id="observer-footer">Observer: Sardinia Radio Telescope (SRT)</span>
      <span>Output: Auxiliary Telescope legacy trajectory format</span>
    </footer>
  </main>
</body>
</html>'''


def render_dynamic_fields(target_family: str, mode: str) -> str:
    """Render target- and mode-specific form fields for dynamic replacement."""
    family = target_family if target_family in {"astronomical", "solar-system", "satellite"} else "astronomical"
    selected_mode = mode if mode in {"track", "cross-scan", "map"} else "track"

    chunks: list[str] = ['<div class="dynamic-block">']
    if family == "astronomical":
        chunks.append('''
          <div class="astronomical-source-grid target-grid">
            <div class="source-search-field">
              <span class="field-label">Search SIMBAD source</span>
              <div class="source-input-row">
                <div class="source-autocomplete">
                  <input name="source" id="simbad-source-input" type="text" required
                    placeholder="W3(OH)" autocomplete="off" aria-autocomplete="list"
                    aria-controls="simbad-suggestions" aria-expanded="false">
                  <input name="source_canonical" id="simbad-source-canonical" type="hidden" value="">
                  <div id="simbad-suggestions" class="autocomplete-menu" role="listbox" hidden></div>
                </div>
                <button class="favorite-toggle" type="button" id="simbad-favorite-toggle"
                  aria-label="Add source to favorites" title="Add source to favorites" disabled>
                  <span aria-hidden="true">☆</span>
                </button>
              </div>
              <div id="simbad-source-status" class="source-message" role="status" aria-live="polite"></div>
            </div>
            <label><span>Favorites</span>
              <select id="simbad-favorites-select">
                <option value="">No favorites saved</option>
              </select>
            </label>
          </div>
          <p class="hint source-hint">Remote SIMBAD search. Type at least two characters. Suggestions are limited; continue typing to refine the search, or enter a complete source name directly.</p>''')
    elif family == "solar-system":
        options = "".join(
            f'<option value="{escape(body.value)}">{escape(body.value.title())}</option>'
            for body in SolarSystemBody
        )
        chunks.append(f'''
          <div class="grid one target-grid">
            <label><span>Solar System body</span>
              <select name="body">{options}</select>
            </label>
          </div>''')
    else:
        chunks.append('''
          <div class="target-grid satellite-target-grid">
            <div class="tle-catalog-layout">
              <div class="tle-source-column">
                <label class="tle-source-select"><span>TLE source</span>
                  <select name="tle_source" id="tle-source">
                    <option value="download">Download fresh TLE</option>
                    <option value="upload">Upload catalog file</option>
                    <option value="paste">Paste TLE manually</option>
                  </select>
                </label>

                <div id="tle-download-panel" class="tle-source-panel">
                  <div class="tle-action-row">
                    <button class="secondary" type="button" id="tle-download-button">Download</button>
                    <span id="tle-download-check" class="catalog-check" hidden aria-label="TLE catalog ready">✓</span>
                    <span id="tle-download-status" class="source-message" role="status" aria-live="polite"></span>
                  </div>
                </div>

                <div id="tle-upload-panel" class="tle-source-panel" hidden>
                  <div class="tle-action-row">
                    <button class="secondary" type="button" id="tle-upload-button">Upload file</button>
                    <button class="secondary" type="button" id="tle-open-folder-button">Open TLE folder</button>
                    <span id="tle-upload-check" class="catalog-check" hidden aria-label="TLE catalog ready">✓</span>
                    <span id="tle-upload-status" class="source-message" role="status" aria-live="polite"></span>
                  </div>
                  <input id="tle-catalog-file" type="file" accept=".tle,.txt,text/plain" hidden>
                </div>
              </div>

              <div id="satellite-catalog-selection" class="satellite-catalog-selection" hidden>
                <span class="field-label">Satellite</span>
                <div class="satellite-autocomplete">
                  <input name="satellite_name" id="satellite-name-input" type="text"
                    placeholder="Start typing a satellite name" autocomplete="off"
                    aria-autocomplete="list" aria-controls="satellite-suggestions"
                    aria-expanded="false">
                  <input name="tle_catalog_id" id="tle-catalog-id" type="hidden" value="">
                  <div id="satellite-suggestions" class="autocomplete-menu" role="listbox" hidden></div>
                </div>
                <p id="satellite-catalog-hint" class="hint satellite-catalog-hint"></p>
              </div>
            </div>

            <div id="tle-paste-panel" class="tle-source-panel" hidden>
              <label><span>Named TLE</span>
                <textarea name="tle_text" id="tle-text" rows="5"
                  placeholder="SATELLITE NAME&#10;1 ...&#10;2 ..."></textarea>
              </label>
            </div>
          </div>''')

    if selected_mode != "track":
        chunks.append('''
          <div class="grid one scan-grid">
            <label><span>Half span <small>deg</small></span>
              <input name="half_span_deg" type="number" step="any" value="2">
            </label>
          </div>''')

    chunks.append("</div>")
    return "".join(chunks)
__all__ = ["render_dynamic_fields", "render_index"]
