(() => {
  "use strict";

  function status(message, kind) {
    const node = document.getElementById("generation-status");
    if (!node) return;
    node.textContent = message;
    node.className = "generation-status" + (kind ? " " + kind : "");
  }

  function filenameFromDisposition(value) {
    if (!value) return "trajectory.txt";
    const match = /filename="([^"]+)"/i.exec(value);
    return match ? match[1] : "trajectory.txt";
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

  async function fallbackDynamicFields() {
    if (window.htmx) return;
    const family = document.getElementById("target-family");
    const mode = document.getElementById("trajectory-mode");
    const target = document.getElementById("dynamic-fields");
    if (!family || !mode || !target) return;

    async function refresh() {
      if (window.htmx) return;
      const params = new URLSearchParams({ target_family: family.value, mode: mode.value });
      try {
        const response = await fetch(`/ui/fields?${params}`);
        if (response.ok) target.innerHTML = await response.text();
      } catch (_) {
        // The initial server-rendered fields remain usable if the request fails.
      }
    }
    family.addEventListener("change", refresh);
    mode.addEventListener("change", refresh);
  }

  document.addEventListener("DOMContentLoaded", () => {
    const form = document.querySelector("[data-generate-form]");
    if (form) {
      form.addEventListener("submit", (event) => {
        event.preventDefault();
        submitTrajectory(form);
      });
    }
    fallbackDynamicFields();
  });
})();
