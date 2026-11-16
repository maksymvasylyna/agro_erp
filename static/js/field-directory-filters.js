(function () {
  "use strict";
  const root = document.getElementById("field-directory-filters");
  const results = document.getElementById("fields-results");
  if (!root || !results) return;

  const keys = ["cluster", "company", "culture"];
  const endpoint = window.location.pathname;
  const search = document.getElementById("field-search");
  const reset = document.getElementById("reset-directory-filters");
  const status = document.getElementById("directory-filter-status");
  const panels = {};
  const triggers = {};
  let activeKey = null;
  let controller = null;
  let serial = 0;
  let searchTimer = null;

  keys.forEach(function (key) {
    panels[key] = document.querySelector('[data-directory-panel="' + key + '"]');
    triggers[key] = document.querySelector('[data-directory-trigger="' + key + '"]');
    if (!panels[key] || !triggers[key]) return;
    // The reference table is scrollable; put menus outside that container.
    document.body.appendChild(panels[key]);
    panels[key].hidden = true;
    triggers[key].addEventListener("click", function (event) {
      event.stopPropagation();
      if (activeKey === key) return closePanel();
      closePanel();
      activeKey = key;
      panels[key].hidden = false;
      triggers[key].setAttribute("aria-expanded", "true");
      positionPanel(key);
    });
  });

  function closePanel() {
    if (activeKey && panels[activeKey]) {
      panels[activeKey].hidden = true;
      triggers[activeKey].setAttribute("aria-expanded", "false");
    }
    activeKey = null;
  }

  function positionPanel(key) {
    const panel = panels[key];
    const button = triggers[key];
    if (!panel || !button || panel.hidden) return;
    const rect = button.getBoundingClientRect();
    const width = Math.min(315, window.innerWidth - 16);
    panel.style.width = Math.max(220, width) + "px";
    const height = panel.getBoundingClientRect().height;
    let top = rect.bottom + 5;
    if (top + height > window.innerHeight - 8 && rect.top > height + 8) {
      top = rect.top - height - 5;
    }
    panel.style.top = Math.max(8, Math.min(top, window.innerHeight - height - 8)) + "px";
    panel.style.left = Math.max(8, Math.min(rect.left, window.innerWidth - width - 8)) + "px";
  }

  function choicesFor(key) {
    return Array.from(panels[key].querySelectorAll("[data-directory-option]"));
  }

  function updateLabel(key) {
    const inputs = choicesFor(key);
    const selected = inputs.filter(function (input) { return input.checked; }).length;
    const all = panels[key].querySelector("[data-select-all]");
    all.checked = inputs.length > 0 && selected === inputs.length;
    all.indeterminate = selected > 0 && selected < inputs.length;
    all.disabled = inputs.length === 0;
    if (selected === inputs.length) {
      triggers[key].querySelector("[data-selection-label]").textContent = "Усі";
    } else if (selected === 0) {
      triggers[key].querySelector("[data-selection-label]").textContent = "Нічого не обрано";
    } else {
      triggers[key].querySelector("[data-selection-label]").textContent =
        "Обрано " + selected + " із " + inputs.length;
    }
    triggers[key].disabled = inputs.length === 0;
  }

  function filterPopup(key) {
    const term = (panels[key].querySelector("[data-directory-search]").value || "")
      .trim().toLocaleLowerCase("uk");
    choicesFor(key).forEach(function (input) {
      const item = input.closest(".directory-filter-item");
      item.hidden = !item.textContent.toLocaleLowerCase("uk").includes(term);
    });
  }

  function renderOptions(key, entries, selected) {
    const container = panels[key].querySelector("[data-directory-options]");
    const selectedIds = new Set((selected || []).map(String));
    const savedSearch = panels[key].querySelector("[data-directory-search]").value;
    container.replaceChildren();

    if (!entries.length) {
      const empty = document.createElement("span");
      empty.className = "text-muted small";
      empty.textContent = "Немає значень у поточній вибірці.";
      container.appendChild(empty);
    }

    entries.forEach(function (entry) {
      const label = document.createElement("label");
      label.className = "directory-filter-item";
      const input = document.createElement("input");
      input.type = "checkbox";
      input.name = key;
      input.value = String(entry.id);
      input.checked = selectedIds.has(String(entry.id));
      input.className = "form-check-input mt-0";
      input.dataset.directoryOption = "";
      const text = document.createElement("span");
      text.textContent = entry.name;
      label.append(input, text);
      container.appendChild(label);
    });
    panels[key].querySelector("[data-directory-search]").value = savedSearch;
    updateLabel(key);
    filterPopup(key);
    if (activeKey === key) positionPanel(key);
  }

  function buildURL(changed) {
    const url = new URL(endpoint, window.location.href);
    const q = search.value.trim();
    if (q) url.searchParams.set("q", q);
    if (changed === "reset" || changed === "q") return url;

    const changedIndex = keys.indexOf(changed);
    keys.forEach(function (key, index) {
      // A parent change resets child selections, never retaining stale options.
      if (changedIndex !== -1 && index > changedIndex) return;
      const choices = choicesFor(key);
      const checked = choices.filter(function (input) { return input.checked; });
      if (checked.length === choices.length) return;
      if (checked.length === 0) {
        url.searchParams.append(key, "__none__");
      } else {
        checked.forEach(function (input) { url.searchParams.append(key, input.value); });
      }
    });
    return url;
  }

  async function updateResults(changed) {
    const target = buildURL(changed);
    if (controller) controller.abort();
    controller = new AbortController();
    const id = ++serial;
    status.textContent = "Оновлюємо поля…";
    try {
      const response = await fetch(target.toString(), {
        method: "GET",
        credentials: "same-origin",
        headers: { "X-Requested-With": "XMLHttpRequest", "Accept": "application/json" },
        signal: controller.signal
      });
      if (!response.ok) throw new Error("HTTP " + response.status);
      const data = await response.json();
      if (id !== serial) return;

      const parsed = new DOMParser().parseFromString(data.html, "text/html");
      const newResults = parsed.getElementById("fields-results");
      const oldResults = document.getElementById("fields-results");
      if (!newResults || !oldResults) throw new Error("Missing result fragment");
      oldResults.replaceWith(newResults);

      keys.forEach(function (key) {
        renderOptions(key, data.options[key] || [], data.checked[key] || []);
      });
      const canonical = buildURL();
      window.history.replaceState(null, "", canonical.pathname + canonical.search);
      status.textContent = "";
    } catch (error) {
      if (error.name === "AbortError") return;
      status.textContent = "Не вдалося оновити таблицю. Відкриваємо сторінку…";
      window.location.assign(target.toString());
    }
  }

  document.addEventListener("click", function (event) {
    if (activeKey && !panels[activeKey].contains(event.target) &&
        !triggers[activeKey].contains(event.target)) closePanel();
  });
  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape" && activeKey) {
      const key = activeKey;
      closePanel();
      triggers[key].focus();
    }
  });
  window.addEventListener("resize", function () { if (activeKey) positionPanel(activeKey); });
  window.addEventListener("scroll", function () { if (activeKey) positionPanel(activeKey); }, { passive: true });

  document.addEventListener("change", function (event) {
    const panel = event.target.closest("[data-directory-panel]");
    if (!panel) return;
    const key = panel.dataset.directoryPanel;
    if (event.target.matches("[data-select-all]")) {
      const checked = event.target.checked;
      choicesFor(key).forEach(function (input) { input.checked = checked; });
    } else if (!event.target.matches("[data-directory-option]")) {
      return;
    }
    updateLabel(key);
    updateResults(key);
  });
  document.addEventListener("input", function (event) {
    if (event.target.matches("[data-directory-search]")) {
      filterPopup(event.target.dataset.directorySearch);
    }
  });
  search.addEventListener("input", function () {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(function () { updateResults("q"); }, 300);
  });
  reset.addEventListener("click", function () {
    closePanel();
    clearTimeout(searchTimer);
    search.value = "";
    keys.forEach(function (key) { panels[key].querySelector("[data-directory-search]").value = ""; });
    updateResults("reset");
  });

  keys.forEach(updateLabel);
  window.addEventListener("popstate", function () { window.location.reload(); });
})();
