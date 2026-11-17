/* AgroERP read-only crop rotation: cascading multi-select filters, no Apply button. */
(function () {
  "use strict";
  const root = document.getElementById("rotation-page");
  if (!root) return;

  const endpoint = "/structure/rotation";
  const csvEndpoint = "/structure/rotation/csv";
  const facetOrder = ["clusters", "companies", "masses", "cultures"];
  const results = document.getElementById("rotation-results");
  const status = document.getElementById("rotation-status");
  const csvLink = document.getElementById("rotation-csv");
  const searchInput = document.getElementById("rotation-query");
  let currentController = null;
  let serial = 0;
  let searchTimer = null;

  function params() {
    return new URLSearchParams(window.location.search);
  }

  function syncCsv(p) {
    const url = new URL(csvEndpoint, window.location.origin);
    url.search = p.toString();
    csvLink.href = url.toString();
  }

  function clearFollowing(p, key) {
    const i = facetOrder.indexOf(key);
    if (i !== -1) {
      facetOrder.slice(i + 1).forEach(function (later) {
        p.delete(later);
      });
    }
  }

  function buildOption(key, item, checked) {
    const label = document.createElement("label");
    label.className = "rotation-option";
    const box = document.createElement("input");
    box.type = "checkbox";
    box.className = "form-check-input";
    box.setAttribute("data-rot-check", key);
    box.value = String(item.id);
    box.checked = checked.has(String(item.id));
    const name = document.createElement("span");
    name.textContent = item.name;
    label.append(box, name);
    return label;
  }

  function filterOptionSearch(key) {
    const field = document.querySelector('[data-rot-option-search="' + key + '"]');
    const panel = document.querySelector('[data-rot-options="' + key + '"]');
    if (!field || !panel) return;
    const term = field.value.trim().toLocaleLowerCase("uk");
    panel.querySelectorAll("label.rotation-option").forEach(function (label) {
      label.hidden = !label.textContent.toLocaleLowerCase("uk").includes(term);
    });
  }

  function renderFacets(facets, checked) {
    facetOrder.forEach(function (key) {
      const holder = document.querySelector('[data-rot-options="' + key + '"]');
      const caption = document.querySelector('[data-rot-caption="' + key + '"]');
      if (!holder) return;
      const options = facets[key] || [];
      const current = new Set((checked[key] || []).map(String));
      const nodes = options.map(function (item) { return buildOption(key, item, current); });
      if (!nodes.length) {
        const empty = document.createElement("span");
        empty.className = "small text-muted";
        empty.textContent = "Немає варіантів";
        nodes.push(empty);
      }
      holder.replaceChildren(...nodes);
      if (caption) {
        caption.textContent = current.size === options.length
          ? "Усі (" + options.length + ")"
          : current.size + " із " + options.length;
      }
      filterOptionSearch(key);
    });
  }

  async function load(p, changeHistory) {
    const current = ++serial;
    if (currentController) currentController.abort();
    currentController = new AbortController();
    status.textContent = "Оновлюємо звіт…";

    const url = new URL(endpoint, window.location.origin);
    url.search = p.toString();
    try {
      const response = await fetch(url.toString(), {
        headers: {
          "X-Requested-With": "XMLHttpRequest",
          "Accept": "application/json"
        },
        signal: currentController.signal,
        credentials: "same-origin"
      });
      if (!response.ok) throw new Error("Помилка запиту: HTTP " + response.status);
      const payload = await response.json();
      if (current !== serial) return;
      results.innerHTML = payload.html;
      renderFacets(payload.facets, payload.checked);
      syncCsv(p);
      if (changeHistory) {
        const location = new URL(url.toString());
        window.history.replaceState({}, "", location.pathname + location.search);
      }
      status.textContent = "Показано " + payload.field_count + " полів";
    } catch (error) {
      if (error.name === "AbortError") return;
      status.textContent = "Не вдалося оновити: " + error.message;
    }
  }

  function fromControls(key, value) {
    const p = params();
    p.delete("page");
    if (value === "" || value == null) {
      p.delete(key);
    } else {
      p.set(key, String(value));
    }
    if (key === "year_from" || key === "year_to") {
      const from = Number(p.get("year_from") || document.getElementById("rotation-year-from").value);
      const to = Number(p.get("year_to") || document.getElementById("rotation-year-to").value);
      if (from > to) {
        if (key === "year_from") {
          document.getElementById("rotation-year-to").value = String(from);
          p.set("year_to", String(from));
        } else {
          document.getElementById("rotation-year-from").value = String(to);
          p.set("year_from", String(to));
        }
      }
      // A prior crop year may no longer be in the visible year range.
      const cropYear = Number(p.get("crop_year"));
      if (cropYear && (cropYear < Number(p.get("year_from")) ||
          cropYear > Number(p.get("year_to")))) {
        p.delete("crop_year");
        document.getElementById("rotation-crop-year").value = "";
      }
      facetOrder.forEach(function (item) { p.delete(item); });
    }
    if (key === "crop_year") {
      p.delete("cultures");
    }
    load(p, true);
  }

  function fromFacet(key, method) {
    const p = params();
    p.delete(key);
    p.delete("page");
    if (method === "none") {
      p.append(key, "__none__");
    } else if (method !== "all") {
      const inputs = Array.from(document.querySelectorAll('[data-rot-check="' + key + '"]'));
      const selected = inputs.filter(function (item) { return item.checked; });
      if (!selected.length) {
        p.append(key, "__none__");
      } else if (selected.length < inputs.length) {
        selected.forEach(function (item) { p.append(key, item.value); });
      }
    }
    clearFollowing(p, key);
    load(p, true);
  }

  // Facet checkboxes are dynamically re-rendered after every response.
  root.addEventListener("change", function (event) {
    const box = event.target.closest("[data-rot-check]");
    if (box) {
      fromFacet(box.getAttribute("data-rot-check"), "checks");
      return;
    }
    const control = event.target.closest("[data-rot-param]");
    if (control && control !== searchInput) {
      fromControls(control.getAttribute("data-rot-param"), control.value);
    }
  });

  root.addEventListener("input", function (event) {
    if (event.target === searchInput) {
      clearTimeout(searchTimer);
      searchTimer = setTimeout(function () {
        fromControls("q", searchInput.value.trim());
      }, 320);
      return;
    }
    const lookup = event.target.closest("[data-rot-option-search]");
    if (lookup) filterOptionSearch(lookup.getAttribute("data-rot-option-search"));
  });

  root.addEventListener("click", function (event) {
    const all = event.target.closest("[data-rot-all]");
    const none = event.target.closest("[data-rot-none]");
    const nextPage = event.target.closest("[data-rot-page]");
    if (all) return fromFacet(all.getAttribute("data-rot-all"), "all");
    if (none) return fromFacet(none.getAttribute("data-rot-none"), "none");
    if (nextPage && !nextPage.disabled) {
      const p = params();
      p.set("page", nextPage.getAttribute("data-rot-page"));
      load(p, true);
    }
  });

  document.getElementById("rotation-reset").addEventListener("click", function () {
    clearTimeout(searchTimer);
    root.querySelectorAll("[data-rot-param]").forEach(function (control) {
      const defaultOption = control.querySelector("option");
      if (control.tagName === "SELECT") {
        if (control.id === "rotation-year-to") {
          control.value = control.options[control.options.length - 1].value;
        } else {
          control.value = defaultOption ? defaultOption.value : "";
        }
      } else control.value = "";
    });
    root.querySelectorAll("[data-rot-option-search]").forEach(function (box) { box.value = ""; });
    load(new URLSearchParams(), true);
  });

  // Close sibling facet menus but allow checking multiple options in one menu.
  root.querySelectorAll("[data-rot-facet]").forEach(function (facet) {
    facet.addEventListener("toggle", function () {
      if (!facet.open) return;
      root.querySelectorAll("[data-rot-facet]").forEach(function (other) {
        if (other !== facet) other.open = false;
      });
    });
  });

  syncCsv(params());
})();
