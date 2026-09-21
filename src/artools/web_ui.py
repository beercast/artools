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
        <p class="eyebrow">Sardinia Radio Telescope site</p>
        <h1>ARTools</h1>
        <p class="subtitle">Auxiliary Telescope trajectory generator</p>
      </div>
      <div class="status-chip"><span class="status-dot"></span>Local server</div>
    </header>

    <section class="panel">
      <form id="trajectory-form" action="/generate" method="post" enctype="multipart/form-data" data-generate-form>
        <div class="section-heading">
          <div><span class="step">01</span><h2>Trajectory</h2></div>
          <p>Choose the controlled system, target family, and trajectory mode.</p>
        </div>

        <div class="grid three">
          <label>
            <span>Controlled system</span>
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
            <input name="output_name" type="text" value="trajectory.txt" required autocomplete="off">
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
      <span>Observer: SRT site</span>
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
              <span class="field-label">SIMBAD source name</span>
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
          <p class="hint source-hint">Type at least two characters to search SIMBAD.</p>''')
        chunks.append(_atmosphere_fields())
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
        chunks.append(_atmosphere_fields())
    else:
        chunks.append('''
          <div class="target-grid">
            <div class="field-label">Satellite TLE source</div>
            <p class="hint">Provide exactly one: paste a named three-line TLE, upload a TLE file, or enter a CelesTrak satellite name.</p>
            <div class="grid satellite-grid">
              <label><span>Paste named TLE</span>
                <textarea name="tle_text" rows="5" placeholder="SATELLITE NAME&#10;1 ...&#10;2 ..."></textarea>
              </label>
              <label><span>Upload TLE file</span>
                <input name="tle_file" type="file" accept=".tle,.txt,text/plain">
              </label>
              <label><span>CelesTrak name</span>
                <input name="catalog_name" type="text" placeholder="EUTELSAT HOTBIRD 13B" autocomplete="off">
              </label>
            </div>
          </div>
          <details class="advanced">
            <summary>Satellite refraction</summary>
            <div class="grid three detail-grid">
              <label class="check-label">
                <input name="refraction" type="checkbox" value="true">
                <span>Enable legacy-compatible refraction</span>
              </label>
              <label><span>Frequency <small>GHz</small></span>
                <input name="refraction_frequency_ghz" type="number" min="0.000001" step="any" value="22">
              </label>
              <label><span>Observer altitude <small>m</small></span>
                <input name="refraction_altitude_m" type="number" min="0" step="any" value="650">
              </label>
            </div>
          </details>''')

    if selected_mode != "track":
        chunks.append('''
          <div class="grid one scan-grid">
            <label><span>Half span <small>deg</small></span>
              <input name="half_span_deg" type="number" step="any" value="2">
            </label>
          </div>''')

    chunks.append("</div>")
    return "".join(chunks)


def _atmosphere_fields() -> str:
    return '''
      <details class="advanced">
        <summary>Atmospheric parameters</summary>
        <div class="grid four detail-grid">
          <label><span>Pressure <small>hPa</small></span>
            <input name="pressure_hpa" type="number" min="0" step="any" value="0">
          </label>
          <label><span>Temperature <small>deg C</small></span>
            <input name="temperature_c" type="number" step="any" value="0">
          </label>
          <label><span>Relative humidity</span>
            <input name="relative_humidity" type="number" min="0" step="any" value="0">
          </label>
          <label><span>Wavelength <small>m</small></span>
            <input name="wavelength_m" type="number" min="0.000000001" step="any" value="0.013627">
          </label>
        </div>
      </details>'''


__all__ = ["render_dynamic_fields", "render_index"]
