/* Simple Excel-style crop filters: one popup per year, no controls above table. */
(function () {
  "use strict";
  const root = document.getElementById("rotation-page");
  const popup = document.getElementById("rotation-crop-menu");
  if (!root || !popup) return;

  const search = document.getElementById("rotation-crop-search");
  const all = document.getElementById("rotation-select-all");
  const optionsList = document.getElementById("rotation-menu-options");
  const apply = document.getElementById("rotation-apply");
  const clear = document.getElementById("rotation-clear");
  const title = document.getElementById("rotation-menu-title");
  const exportLink = document.getElementById("rotation-export");
  const results = document.getElementById("rotation-results");

  let filterOptions = window.agroRotationFilters || {};
  let currentYear = null;
  let trigger = null;
  let requestController = null;
  let serial = 0;

  function inputs() {
    return Array.from(optionsList.querySelectorAll("input[type=checkbox]"));
  }

  function syncAll() {
    const boxes = inputs();
    const checked = boxes.filter(box => box.checked).length;
    all.checked = boxes.length > 0 && checked === boxes.length;
    all.indeterminate = checked > 0 && checked < boxes.length;
  }

  function filterSearch() {
    const term = search.value.trim().toLocaleLowerCase("uk");
    optionsList.querySelectorAll(".rotation-crop-option").forEach(label => {
      label.hidden = !label.textContent.toLocaleLowerCase("uk").includes(term);
    });
  }

  function position() {
    if (!trigger || popup.hidden) return;
    const bounds = trigger.getBoundingClientRect();
    const width = popup.offsetWidth;
    const height = popup.offsetHeight;
    const left = Math.max(10, Math.min(bounds.left, window.innerWidth - width - 10));
    let top = bounds.bottom + 6;
    if (top + height > window.innerHeight - 10) {
      top = Math.max(10, bounds.top - height - 6);
    }
    popup.style.left = left + "px";
    popup.style.top = top + "px";
  }

  function close() {
    popup.hidden = true;
    if (trigger) trigger.setAttribute("aria-expanded", "false");
    currentYear = null;
    trigger = null;
  }

  function open(year, button) {
    if (currentYear === year && !popup.hidden) {
      close();
      return;
    }
    close();
    currentYear = year;
    trigger = button;
    const config = filterOptions[String(year)] || { options: [], checked: [] };
    const checked = new Set(config.checked.map(String));
    title.textContent = "Культура · " + year;
    search.value = "";
    optionsList.replaceChildren();
    config.options.forEach(item => {
      const label = document.createElement("label");
      label.className = "rotation-crop-option";
      const input = document.createElement("input");
      input.className = "form-check-input";
      input.type = "checkbox";
      input.value = String(item.id);
      input.checked = checked.has(input.value);
      const name = document.createElement("span");
      name.textContent = String(item.name);
      label.append(input, name);
      optionsList.appendChild(label);
    });
    syncAll();
    popup.hidden = false;
    button.setAttribute("aria-expanded", "true");
    position();
    search.focus();
  }

  async function refresh(params) {
    const currentRequest = ++serial;
    if (requestController) requestController.abort();
    requestController = new AbortController();
    const status = document.getElementById("rotation-status");
    if (status) status.textContent = "Оновлення…";
    const url = new URL("/structure/rotation", window.location.origin);
    url.search = params.toString();
    try {
      const response = await fetch(url.toString(), {
        headers: { "X-Requested-With": "XMLHttpRequest", "Accept": "application/json" },
        credentials: "same-origin",
        signal: requestController.signal
      });
      if (!response.ok) throw new Error("HTTP " + response.status);
      const data = await response.json();
      if (currentRequest !== serial) return;
      filterOptions = data.filters;
      results.innerHTML = data.html;
      const exportUrl = new URL("/structure/rotation/csv", window.location.origin);
      exportUrl.search = params.toString();
      exportLink.href = exportUrl.toString();
      window.history.replaceState({}, "", url.pathname + url.search);
    } catch (error) {
      if (error.name === "AbortError") return;
      if (status) status.textContent = "Не вдалося оновити таблицю. " + error.message;
    }
  }

  function updateYear(clearOnly) {
    if (currentYear == null) return;
    const year = currentYear;
    const selected = inputs().filter(x => x.checked).map(x => x.value);
    const length = inputs().length;
    const params = new URLSearchParams(window.location.search);
    const key = "crop_" + year;
    params.delete(key);
    if (!clearOnly) {
      if (selected.length === 0) params.append(key, "__none__");
      else if (selected.length !== length) {
        selected.forEach(value => params.append(key, value));
      }
    }
    close();
    refresh(params);
  }

  root.addEventListener("click", event => {
    const button = event.target.closest("[data-rotation-year]");
    if (button) {
      event.stopPropagation();
      open(Number(button.getAttribute("data-rotation-year")), button);
    }
  });

  search.addEventListener("input", filterSearch);
  optionsList.addEventListener("change", syncAll);
  all.addEventListener("change", () => {
    const visible = inputs().filter(box => !box.closest(".rotation-crop-option").hidden);
    visible.forEach(box => { box.checked = all.checked; });
    syncAll();
  });
  apply.addEventListener("click", () => updateYear(false));
  clear.addEventListener("click", () => updateYear(true));

  document.addEventListener("click", event => {
    if (!popup.hidden && !popup.contains(event.target) &&
        !event.target.closest("[data-rotation-year]")) close();
  });
  document.addEventListener("keydown", event => {
    if (event.key === "Escape") close();
  });
  window.addEventListener("resize", position);
  window.addEventListener("scroll", position, true);

  const initial = new URL("/structure/rotation/csv", window.location.origin);
  initial.search = window.location.search;
  exportLink.href = initial.toString();
})();
