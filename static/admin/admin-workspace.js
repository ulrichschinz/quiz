/* Admin workspace — inline save for the quiz editor (Phase 1).
 *
 * Progressive enhancement over the existing per-entity <form>s. Each form marked
 * `data-inline` is intercepted: instead of POST -> 303 -> full page reload (which
 * lost the scroll position on every save, incl. "+ Option"), we POST via fetch()
 * with an `X-Inline: 1` header and act on the response in place. The page never
 * reloads and never jumps to the top.
 *
 * Server contract (see app/interfaces/web/admin.py):
 *   - replace/append  -> 200 + the re-rendered fragment HTML
 *   - remove (delete) -> 204 No Content
 *   - save (singleton)-> 204 No Content
 *   - validation error-> 422 + a plain-text German message
 *
 * Mode is read from the clicked button (`data-mode`) or the form (`data-mode`),
 * default "replace". Without JS the same forms still POST and 303-redirect.
 *
 * Data-loss guards: a "• ungespeichert" marker appears on edit and a
 * beforeunload warning fires while any inline form stays dirty.
 */
(function () {
  "use strict";

  var HIDE_SAVED_MS = 2500;

  function statusEl(form) {
    var el = form.querySelector(":scope > .ws-status");
    if (!el) {
      el = document.createElement("span");
      el.className = "ws-status";
      form.appendChild(el);
    }
    return el;
  }

  function setStatus(form, kind, text) {
    var el = statusEl(form);
    el.className = "ws-status ws-status-" + kind;
    el.textContent = text;
    if (el._t) {
      clearTimeout(el._t);
      el._t = null;
    }
    if (kind === "saved") {
      el._t = setTimeout(function () {
        if (el.parentNode) el.parentNode.removeChild(el);
      }, HIDE_SAVED_MS);
    }
  }

  function markDirty(form) {
    form.dataset.dirty = "1";
    setStatus(form, "dirty", "• ungespeichert");
  }

  function clearDirty(form) {
    delete form.dataset.dirty;
  }

  function anyDirty() {
    return !!document.querySelector("form[data-inline][data-dirty]");
  }

  // --- save flow ----------------------------------------------------------
  function submit(form, submitter) {
    var mode = (submitter && submitter.dataset.mode) || form.dataset.mode || "replace";
    var action = (submitter && submitter.formAction) || form.action;

    setStatus(form, "saving", "speichert …");

    fetch(action, {
      method: "POST",
      headers: { "X-Inline": "1" },
      body: new FormData(form),
      credentials: "same-origin",
    })
      .then(function (res) {
        // A followed redirect (e.g. session expired -> /login) is not a fragment.
        if (res.redirected) {
          window.location.reload();
          return null;
        }
        if (!res.ok) {
          return res.text().then(function (msg) {
            setStatus(form, "error", msg.trim() || "Nicht gespeichert – bitte erneut.");
            throw new Error("save failed");
          });
        }
        return res.status === 204 ? "" : res.text();
      })
      .then(function (html) {
        if (html === null) return; // redirected
        apply(form, mode, html);
      })
      .catch(function () {
        // Network error: keep the dirty state + input, surface a retry hint.
        if (form.querySelector(".ws-status-error")) return;
        setStatus(form, "error", "Netzwerkfehler – nicht gespeichert.");
      });
  }

  function apply(form, mode, html) {
    if (mode === "remove") {
      var card = form.closest("[data-card]");
      var details = form.closest("details[data-question-card]"); // option delete: keep the card
      if (card) card.remove();
      if (details && details !== card) refreshSummary(details);
      return;
    }
    if (mode === "save") {
      clearDirty(form);
      setStatus(form, "saved", "✓ gespeichert");
      return;
    }
    if (mode === "append") {
      form.insertAdjacentHTML("beforebegin", html);
      var added = form.previousElementSibling;
      form.reset();
      clearDirty(form);
      setStatus(form, "saved", "✓ hinzugefügt");
      flashSaved(added);
      if (added && added.matches && added.matches("details[data-question-card]")) {
        wireDetails(added); // a freshly added question — open it so it can be filled
        added.open = true;
        persistOpen(added);
        refreshSummary(added);
        ensureToggleAll();
      } else if (added && added.querySelector && added.querySelector('form[action*="/admin/dimensions/"]')) {
        syncDimensionOptions(added); // new dimension → make it selectable for questions
      } else {
        var host = form.closest("details[data-question-card]"); // an added option
        if (host) refreshSummary(host);
      }
      return;
    }
    // replace (default): swap the [data-replace] block this form lives in.
    var target = form.closest("[data-replace]");
    if (!target) {
      clearDirty(form);
      setStatus(form, "saved", "✓ gespeichert");
      return;
    }
    var holder = document.createElement("div");
    holder.innerHTML = html.trim();
    var fresh = holder.firstElementChild;
    var host = target.closest("details[data-question-card]");
    target.replaceWith(fresh);
    flashSaved(fresh);
    if (host) refreshSummary(host); // question edited → keep the collapsed summary truthful
  }

  function flashSaved(root) {
    if (!root) return;
    var form = root.matches && root.matches("form") ? root : root.querySelector("form[data-inline]");
    if (form) setStatus(form, "saved", "✓ gespeichert");
  }

  // --- delegated listeners ------------------------------------------------
  document.addEventListener("submit", function (e) {
    var form = e.target;
    if (!(form instanceof HTMLFormElement) || !form.hasAttribute("data-inline")) return;
    e.preventDefault();
    submit(form, e.submitter);
  });

  document.addEventListener("input", function (e) {
    var form = e.target.closest && e.target.closest("form[data-inline]");
    if (form) markDirty(form);
  });

  window.addEventListener("beforeunload", function (e) {
    if (anyDirty()) {
      e.preventDefault();
      e.returnValue = "";
    }
  });

  // --- Phase 2: collapsible question cards --------------------------------
  // The <details> `toggle` event does NOT bubble, so each card is wired
  // individually (on load + when a card is appended). Open-state is per quiz
  // (keyed by pathname) + question id, in sessionStorage.
  function openKey(details) {
    return "wsopen:" + window.location.pathname + ":" + (details.dataset.qid || "");
  }

  function persistOpen(details) {
    try {
      window.sessionStorage.setItem(openKey(details), details.open ? "1" : "0");
    } catch (e) {
      /* sessionStorage unavailable — collapse still works, just not remembered */
    }
  }

  function restoreOpen(details) {
    try {
      if (window.sessionStorage.getItem(openKey(details)) === "1") details.open = true;
    } catch (e) {
      /* ignore */
    }
  }

  function wireDetails(details) {
    if (details._wsWired) return;
    details._wsWired = true;
    details.addEventListener("toggle", function () {
      persistOpen(details);
      syncToggleAllLabel();
    });
  }

  // A dimension added inline must appear in every question's dimension <select>,
  // otherwise a question created/edited next would silently bind to the wrong
  // (old first) dimension. The selects are server-rendered once, so patch them.
  function syncDimensionOptions(row) {
    var f = row.querySelector && row.querySelector('form[action*="/admin/dimensions/"]');
    if (!f) return;
    var m = (f.getAttribute("action") || "").match(/\/admin\/dimensions\/(\d+)/);
    if (!m) return;
    var id = m[1];
    var nameInput = row.querySelector('input[name="name_de"]');
    var keyInput = row.querySelector('input[name="key"]');
    var label =
      (nameInput && nameInput.value.trim()) || (keyInput && keyInput.value.trim()) || id;
    document.querySelectorAll('select[name="dimension_id"]').forEach(function (sel) {
      if (sel.querySelector('option[value="' + id + '"]')) return;
      var opt = document.createElement("option");
      opt.value = id;
      opt.textContent = label;
      sel.appendChild(opt);
    });
  }

  function refreshSummary(details) {
    var title = details.querySelector(":scope > summary .ws-summary-title");
    var chip = details.querySelector(":scope > summary .ws-chip");
    var badge = details.querySelector(":scope > summary [data-opt-count]");
    var textInput = details.querySelector('[data-question-form] input[name="text_de"]');
    if (title && textInput) title.textContent = textInput.value.trim() || "Ohne Titel";
    var select = details.querySelector('[data-question-form] select[name="dimension_id"]');
    if (chip && select && select.selectedOptions.length) {
      chip.textContent = select.selectedOptions[0].textContent.trim();
    }
    if (badge) {
      // Option rows render a valueless `data-card`; the add-option form has none.
      var n = details.querySelectorAll("[data-options] [data-card]").length;
      badge.textContent = n + (n === 1 ? " Option" : " Optionen");
    }
  }

  function syncToggleAllLabel() {
    var btn = document.querySelector("[data-ws-toggle-all]");
    if (!btn) return;
    var cards = document.querySelectorAll("details[data-question-card]");
    if (!cards.length) {
      btn.hidden = true;
      return;
    }
    btn.hidden = false;
    var allOpen = Array.prototype.every.call(cards, function (d) {
      return d.open;
    });
    btn.dataset.state = allOpen ? "open" : "closed";
    btn.textContent = allOpen ? "Alle einklappen" : "Alle ausklappen";
  }

  function ensureToggleAll() {
    var btn = document.querySelector("[data-ws-toggle-all]");
    if (!btn) return;
    if (!btn._wsWired) {
      btn._wsWired = true;
      btn.addEventListener("click", function () {
        var open = btn.dataset.state !== "open";
        document.querySelectorAll("details[data-question-card]").forEach(function (d) {
          d.open = open;
          persistOpen(d);
        });
        syncToggleAllLabel();
      });
    }
    syncToggleAllLabel(); // reflect the real open-count, incl. sessionStorage-restored
  }

  function initDetails() {
    document.querySelectorAll("details[data-question-card]").forEach(function (d) {
      restoreOpen(d);
      wireDetails(d);
    });
    ensureToggleAll();
  }

  // --- Phase 2: section rail (one section at a time, hash-driven) ----------
  var SECTIONS = ["meta", "landing", "dimensions", "questions", "tiers", "result"];

  function showSection(name) {
    if (SECTIONS.indexOf(name) === -1) name = SECTIONS[0];
    document.querySelectorAll("[data-ws-section]").forEach(function (s) {
      s.classList.toggle("ws-active", s.dataset.wsSection === name);
    });
    document.querySelectorAll("[data-ws-link]").forEach(function (b) {
      b.classList.toggle("ws-active", b.dataset.wsLink === name);
    });
  }

  function currentSection() {
    return (window.location.hash || "").replace(/^#/, "");
  }

  function initSections() {
    var nav = document.querySelector("[data-ws-nav]");
    if (!nav) return;
    document.body.classList.add("ws-on"); // flip to single-section mode (PE: off without JS)
    nav.addEventListener("click", function (e) {
      var btn = e.target.closest("[data-ws-link]");
      if (!btn) return;
      window.location.hash = btn.dataset.wsLink;
    });
    window.addEventListener("hashchange", function () {
      showSection(currentSection());
    });
    // Encode the active section in the URL on load so it is shareable/durable
    // (replaceState avoids a history entry and a redundant hashchange).
    var start = currentSection();
    if (SECTIONS.indexOf(start) === -1) {
      start = SECTIONS[0];
      try {
        window.history.replaceState(null, "", "#" + start);
      } catch (e) {
        /* ignore */
      }
    }
    showSection(start);
  }

  function init() {
    initSections();
    initDetails();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
