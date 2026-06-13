/* Admin workspace — inline save for the Quiz Studio.
 *
 * Progressive enhancement over the per-entity <form>s inside each studio area.
 * A form marked `data-inline` is intercepted: instead of POST -> 303 -> full
 * reload, we POST via fetch() with an `X-Inline: 1` header and act on the
 * response in place, so editing never reloads or loses the scroll position.
 *
 * Navigation between areas/questions is plain server-side links (real routes) —
 * NOT handled here. This file only does inline saving within a page.
 *
 * Server contract (app/interfaces/web/admin.py):
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
    // Read the *attribute*, not the .formAction property: a submit button with no
    // formaction returns the document URL via the property (HTML spec), which sent
    // saves to the GET page (-> 405) whenever the page path != the form action.
    var explicit = submitter && submitter.getAttribute("formaction");
    var action = explicit || form.action;

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
        if (form.querySelector(".ws-status-error")) return;
        setStatus(form, "error", "Netzwerkfehler – nicht gespeichert.");
      });
  }

  function apply(form, mode, html) {
    if (mode === "remove") {
      var card = form.closest("[data-card]");
      if (card) card.remove();
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
    target.replaceWith(fresh);
    flashSaved(fresh);
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
})();
