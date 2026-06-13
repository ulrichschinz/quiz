/* Weighting UX for the Quiz Studio — the new ranking-based scoring model.
 *
 * Three independent, progressively-enhanced pieces, all delegated at the
 * document level so they survive the inline-save section swaps done by
 * admin-workspace.js (no re-binding needed):
 *
 *   1. Answer options: drag to rank best→worst. On drop we POST the new id
 *      order to data-reorder-url; the server re-derives the weights and returns
 *      the re-rendered [data-options] section, which we swap in.
 *   2. Dimension shares: dragging one "Themen-Anteil" slider proportionally
 *      rebalances the others so the sum stays 100 % (the server renormalises on
 *      save anyway — this is just live feedback).
 *   3. Live preview: a weighted-mean calculator showing the overall score for a
 *      sample answer profile, using the current shares.
 *
 * Without JS the options still rank by their stored order and the shares still
 * save (the sliders POST their raw values; the server renormalises).
 */
(function () {
  "use strict";

  // --- 1. drag-to-rank answer options ------------------------------------
  var dragging = null;

  function optionsSection(el) {
    return el && el.closest ? el.closest("[data-options]") : null;
  }

  document.addEventListener("dragstart", function (e) {
    var row = e.target.closest && e.target.closest(".opt-row[data-opt-id]");
    if (!row || !optionsSection(row)) return;
    dragging = row;
    row.classList.add("opt-dragging");
    if (e.dataTransfer) e.dataTransfer.effectAllowed = "move";
  });

  document.addEventListener("dragend", function () {
    if (dragging) dragging.classList.remove("opt-dragging");
    dragging = null;
  });

  document.addEventListener("dragover", function (e) {
    if (!dragging) return;
    var section = optionsSection(dragging);
    if (!section || !optionsSection(e.target)) return;
    e.preventDefault();
    var after = rowAfter(section, e.clientY);
    if (after == null) {
      section.insertBefore(dragging, section.querySelector(".opt-add"));
    } else if (after !== dragging) {
      section.insertBefore(dragging, after);
    }
  });

  document.addEventListener("drop", function (e) {
    if (!dragging) return;
    e.preventDefault();
    var section = optionsSection(dragging);
    dragging.classList.remove("opt-dragging");
    dragging = null;
    if (section) postOrder(section);
  });

  function rowAfter(section, y) {
    var rows = Array.prototype.slice.call(
      section.querySelectorAll(".opt-row[data-opt-id]:not(.opt-dragging)")
    );
    for (var i = 0; i < rows.length; i++) {
      var box = rows[i].getBoundingClientRect();
      if (y < box.top + box.height / 2) return rows[i];
    }
    return null;
  }

  function postOrder(section) {
    var url = section.getAttribute("data-reorder-url");
    if (!url) return;
    var body = new FormData();
    body.append("quiz_id", section.getAttribute("data-quiz-id") || "");
    section.querySelectorAll(".opt-row[data-opt-id]").forEach(function (r) {
      body.append("order", r.getAttribute("data-opt-id"));
    });
    fetch(url, {
      method: "POST",
      headers: { "X-Inline": "1" },
      body: body,
      credentials: "same-origin",
    })
      .then(function (res) {
        if (res.redirected) {
          window.location.reload();
          return null;
        }
        return res.ok ? res.text() : null;
      })
      .then(function (html) {
        if (html == null) return;
        var holder = document.createElement("div");
        holder.innerHTML = html.trim();
        var fresh = holder.firstElementChild;
        if (fresh) section.replaceWith(fresh);
      })
      .catch(function () {
        /* leave the optimistic DOM order; next real save reconciles */
      });
  }

  // --- 2. dimension share sliders: keep the sum at 100 -------------------
  function weightSliders(panel) {
    return Array.prototype.slice.call(panel.querySelectorAll("[data-weight-slider]"));
  }

  function rebalance(panel, moved) {
    var sliders = weightSliders(panel);
    if (sliders.length < 2) {
      paint(panel);
      return;
    }
    var others = sliders.filter(function (s) {
      return s !== moved;
    });
    var target = 100 - Number(moved.value);
    var othersTotal = others.reduce(function (a, s) {
      return a + Number(s.value);
    }, 0);
    if (othersTotal <= 0) {
      var even = target / others.length;
      others.forEach(function (s) {
        s.value = even;
      });
    } else {
      others.forEach(function (s) {
        s.value = (Number(s.value) / othersTotal) * target;
      });
    }
    paint(panel);
  }

  function paint(panel) {
    var sliders = weightSliders(panel);
    var sum = 0;
    sliders.forEach(function (s) {
      var v = Math.round(Number(s.value));
      sum += v;
      var val = s.parentNode.querySelector("[data-weight-val]");
      if (val) val.textContent = v + "%";
    });
    var sumEl = panel.querySelector("[data-weights-sum]");
    if (sumEl) sumEl.textContent = Math.round(sum) + "%";
    preview(panel);
  }

  // --- 3. live weighted-score preview ------------------------------------
  function preview(panel) {
    var prev = panel.querySelector("[data-preview]");
    if (!prev) return;
    var weights = {};
    weightSliders(panel).forEach(function (s) {
      weights[s.getAttribute("data-dim")] = Number(s.value);
    });
    var totalW = 0;
    var acc = 0;
    prev.querySelectorAll("[data-preview-slider]").forEach(function (s) {
      var w = weights[s.getAttribute("data-dim")] || 0;
      var score = Number(s.value);
      var out = s.parentNode.querySelector("[data-preview-dimscore]");
      if (out) out.textContent = Math.round(score);
      totalW += w;
      acc += score * w;
    });
    var total = totalW > 0 ? Math.round(acc / totalW) : 0;
    var totalEl = prev.querySelector("[data-preview-total]");
    if (totalEl) totalEl.textContent = total;
  }

  document.addEventListener("input", function (e) {
    var t = e.target;
    if (!t || !t.matches) return;
    var panel = t.closest("[data-weights]");
    if (!panel) return;
    if (t.matches("[data-weight-slider]")) {
      rebalance(panel, t);
    } else if (t.matches("[data-preview-slider]")) {
      preview(panel);
    }
  });

  // initial paint for any panel already on the page / freshly swapped in
  function initPanels() {
    document.querySelectorAll("[data-weights]").forEach(paint);
  }
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initPanels);
  } else {
    initPanels();
  }
})();
