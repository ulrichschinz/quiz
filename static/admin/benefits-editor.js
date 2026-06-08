/* Benefits editor — progressive enhancement for the quiz landing form.
 *
 * Replaces the raw `benefits_json` textarea with a row editor (one bilingual
 * bullet per row) plus a live preview. The only field actually posted is the
 * hidden <input name="benefits_json">; this script keeps it in sync with the
 * rows so the server (/admin/quizzes/{id}/landing) needs no changes.
 *
 * Expected data shape: [{ "de": "…", "en": "…" }, …]
 * Rendered publicly as <ul class="ar-list-mono"> in templates/public/landing.html.
 */
(function () {
  "use strict";

  function init() {
    var editor = document.getElementById("benefits-editor");
    if (!editor) return;

    var rows = editor.querySelector("[data-benefits-rows]");
    var addBtn = editor.querySelector("[data-benefits-add]");
    var preview = editor.querySelector("[data-benefits-preview]");
    var hidden = editor.querySelector('input[name="benefits_json"]');
    if (!rows || !addBtn || !hidden) return;

    var form = editor.closest("form");

    var initial = [];
    try {
      var parsed = JSON.parse(editor.dataset.benefits || "[]");
      if (Array.isArray(parsed)) initial = parsed;
    } catch (e) {
      initial = [];
    }

    function makeRow(de, en) {
      var row = document.createElement("div");
      row.className = "ar-benefit-row";
      row.style.cssText =
        "display:flex; gap: var(--ar-space-2); align-items:flex-end; margin-top: var(--ar-space-2);";

      row.appendChild(field("Vorteil (DE)", de, "de"));
      row.appendChild(field("Benefit (EN)", en, "en"));

      var del = document.createElement("button");
      del.type = "button";
      del.className = "ar-btn ar-btn-ghost";
      del.textContent = "✕";
      del.setAttribute("aria-label", "Vorteil entfernen");
      del.addEventListener("click", function () {
        row.parentNode.removeChild(row);
        sync();
      });
      row.appendChild(del);

      return row;
    }

    function field(labelText, value, key) {
      var wrap = document.createElement("div");
      wrap.className = "ar-field";
      wrap.style.flex = "1";

      var label = document.createElement("label");
      label.className = "ar-eyebrow";
      label.textContent = labelText;

      var input = document.createElement("input");
      input.type = "text";
      input.value = value || "";
      input.setAttribute("data-benefit-field", key);
      input.addEventListener("input", sync);

      wrap.appendChild(label);
      wrap.appendChild(input);
      return wrap;
    }

    function collect() {
      var out = [];
      var rowEls = rows.querySelectorAll(".ar-benefit-row");
      for (var i = 0; i < rowEls.length; i++) {
        var de = rowEls[i].querySelector('[data-benefit-field="de"]');
        var en = rowEls[i].querySelector('[data-benefit-field="en"]');
        var deVal = de ? de.value.trim() : "";
        var enVal = en ? en.value.trim() : "";
        if (!deVal && !enVal) continue; // skip empty rows
        out.push({ de: deVal, en: enVal });
      }
      return out;
    }

    function renderPreview(items) {
      if (!preview) return;
      preview.innerHTML = "";
      for (var i = 0; i < items.length; i++) {
        var li = document.createElement("li");
        li.textContent = items[i].de || items[i].en || "";
        preview.appendChild(li);
      }
      preview.style.display = items.length ? "" : "none";
    }

    function sync() {
      var items = collect();
      hidden.value = JSON.stringify(items);
      renderPreview(items);
    }

    addBtn.addEventListener("click", function () {
      rows.appendChild(makeRow("", ""));
      sync();
    });

    if (form) {
      form.addEventListener("submit", sync); // safety net before POST
    }

    // Build initial rows.
    for (var i = 0; i < initial.length; i++) {
      rows.appendChild(makeRow(initial[i].de, initial[i].en));
    }
    sync();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
