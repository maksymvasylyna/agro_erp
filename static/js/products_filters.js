/* Product directory: immediate, faceted filtering without page reload.
   Option values come from actual rendered products in the selected archive tab.
   No fetches or changes to the database are performed. */
(() => {
  "use strict";

  const form = document.getElementById("products-filter-form");
  const table = document.querySelector(".erp-reference-page table.erp-reference-table");
  if (!form || !table) return;

  const search = form.elements.namedItem("q");
  const keys = ["category", "group", "manufacturer"];
  const selects = Object.fromEntries(keys.map((key) => [key, form.elements.namedItem(key)]));
  if (!search || keys.some((key) => !selects[key])) return;

  const rows = Array.from(table.querySelectorAll("tbody tr[data-product-row]"));
  const normal = (value) => (value || "").normalize("NFKC").toLocaleLowerCase("uk-UA").trim();
  const products = rows.map((element) => ({
    element,
    search: normal(element.dataset.search),
    category: element.dataset.category,
    group: element.dataset.group,
    manufacturer: element.dataset.manufacturer,
  }));
  const empty = document.getElementById("products-no-matches");
  const counter = document.getElementById("products-visible-count");
  const reset = document.getElementById("products-reset-filters");

  // WTForms QuerySelectField uses "__None" for the blank option. Read it
  // instead of assuming that the blank value is an empty string.
  const blankValues = Object.fromEntries(keys.map((key) => [key, selects[key].options[0].value]));
  const allOptions = Object.fromEntries(
    keys.map((key) => [key, Array.from(selects[key].options, (option) => option.cloneNode(true))]),
  );

  const update = () => {
    const text = normal(search.value);
    const selected = Object.fromEntries(keys.map((key) => [key, selects[key].value]));
    const matches = (product, excludedKey = null) =>
      (!text || product.search.includes(text)) &&
      keys.every((key) =>
        key === excludedKey ||
        selected[key] === blankValues[key] ||
        product[key] === selected[key],
      );

    let visible = 0;
    for (const product of products) {
      const ok = matches(product);
      product.element.classList.toggle("d-none", !ok);
      if (ok) visible += 1;
    }
    if (empty) empty.classList.toggle("d-none", visible !== 0);
    if (counter) counter.textContent = `Показано ${visible} із ${products.length}`;

    // Faceted dropdowns: calculate each option from the products matching
    // the search and OTHER selected filters, not the filter being rebuilt.
    // Keep the selected value so even an empty combination can be undone.
    for (const key of keys) {
      const available = new Set(products.filter((item) => matches(item, key)).map((item) => item[key]));
      const options = allOptions[key]
        .filter((option) =>
          option.value === blankValues[key] ||
          option.value === selected[key] ||
          available.has(option.value),
        )
        .map((option) => option.cloneNode(true));
      selects[key].replaceChildren(...options);
      selects[key].value = selected[key];
    }
  };

  // Filtering occurs entirely on the client with the whole selected tab
  // already rendered, so neither changing a select nor typing reloads the page.
  form.addEventListener("submit", (event) => event.preventDefault());
  search.addEventListener("input", update);
  for (const key of keys) selects[key].addEventListener("change", update);
  if (reset) {
    reset.addEventListener("click", (event) => {
      event.preventDefault();
      search.value = "";
      for (const key of keys) selects[key].value = blankValues[key];
      update();
    });
  }
  window.addEventListener("pageshow", update);
  update();
})();
