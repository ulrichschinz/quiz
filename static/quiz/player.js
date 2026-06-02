/* Agentic Reach — quiz player.
 * Vanilla, no framework. Fetches the quiz payload, walks the visitor through
 * one question per step with a progress bar, captures the lead at the end and
 * POSTs the submission. Language is driven by the shared DE/EN toggle
 * (window.ARQuizLang) and re-renders on the 'langchange' event.
 */
(function () {
  var root = document.getElementById('quiz-app');
  if (!root) return;
  var slug = root.dataset.slug;
  var stage = document.getElementById('quiz-stage');
  var bar = document.getElementById('quiz-bar');

  var quiz = null;
  var answers = {};      // { question_id: option_id }
  var step = 0;          // 0..N-1 = questions, N = lead form
  var submitting = false;

  function lang() {
    return (window.ARQuizLang && window.ARQuizLang.get()) || root.dataset.defaultLang || 'de';
  }
  function pick(de, en) {
    return lang() === 'en' ? (en || de || '') : (de || en || '');
  }
  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
    });
  }
  function t(de, en) {
    return lang() === 'en' ? en : de;
  }

  function totalSteps() {
    return quiz ? quiz.questions.length + 1 : 1;
  }
  function setProgress() {
    var pct = Math.round((step / totalSteps()) * 100);
    bar.style.width = pct + '%';
  }

  function render() {
    if (!quiz) return;
    setProgress();
    if (step < quiz.questions.length) {
      renderQuestion(quiz.questions[step]);
    } else {
      renderLeadForm();
    }
  }

  function renderQuestion(q) {
    var dim = (quiz.dimensions.find(function (d) { return d.key === q.dimension_key; }) || {});
    var html = '';
    html += '<div class="ar-eyebrow">// ' + esc(pick(dim.name_de, dim.name_en)) +
            ' · ' + (step + 1) + '/' + quiz.questions.length + '</div>';
    html += '<h2 class="ar-display-xs" style="margin:var(--ar-space-3) 0 var(--ar-space-6);">' +
            esc(pick(q.text_de, q.text_en)) + '</h2>';
    if (q.help_de || q.help_en) {
      html += '<p class="ar-small" style="margin-bottom:var(--ar-space-5);opacity:.7;">' +
              esc(pick(q.help_de, q.help_en)) + '</p>';
    }
    q.options.forEach(function (o) {
      var sel = answers[q.id] === o.id ? ' quiz-option--selected' : '';
      html += '<button type="button" class="quiz-option' + sel + '" data-opt="' + o.id + '">' +
              esc(pick(o.label_de, o.label_en)) + '</button>';
    });
    html += '<div style="margin-top:var(--ar-space-6);display:flex;justify-content:space-between;">';
    html += step > 0
      ? '<button type="button" class="ar-btn ar-btn-ghost" id="quiz-back">' + esc(t('← Zurück', '← Back')) + '</button>'
      : '<span></span>';
    html += '</div>';
    stage.innerHTML = html;

    stage.querySelectorAll('[data-opt]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        answers[q.id] = parseInt(btn.dataset.opt, 10);
        step += 1;
        render();
      });
    });
    var back = document.getElementById('quiz-back');
    if (back) back.addEventListener('click', function () { step -= 1; render(); });
  }

  function renderLeadForm() {
    var html = '';
    html += '<div class="ar-eyebrow">// ' + esc(t('Fast geschafft', 'Almost there')) + '</div>';
    html += '<h2 class="ar-display-xs" style="margin:var(--ar-space-3) 0 var(--ar-space-2);">' +
            esc(t('Wohin dürfen wir Ihr Ergebnis senden?', 'Where should we send your result?')) + '</h2>';
    html += '<p class="ar-small" style="margin-bottom:var(--ar-space-6);opacity:.7;">' +
            esc(t('Sie erhalten Ihren Score und die vollständige Auswertung.',
                  'You’ll get your score and the full breakdown.')) + '</p>';
    html += '<form id="quiz-lead" class="ar-form-grid">';
    html += '<div class="ar-field full"><label class="ar-eyebrow">E-Mail*</label>' +
            '<input type="email" name="email" required></div>';
    html += '<div class="ar-field"><label class="ar-eyebrow">' + esc(t('Name', 'Name')) + '</label>' +
            '<input type="text" name="name"></div>';
    html += '<div class="ar-field"><label class="ar-eyebrow">' + esc(t('Firma', 'Company')) + '</label>' +
            '<input type="text" name="company"></div>';
    html += '<div class="ar-field full" style="flex-direction:row;align-items:flex-start;gap:8px;">' +
            '<input type="checkbox" name="consent" id="consent" style="width:auto;margin-top:4px;">' +
            '<label for="consent" class="ar-small">' +
            esc(t('Ich bin einverstanden, kontaktiert zu werden.',
                  'I agree to be contacted.')) + '</label></div>';
    html += '<div class="ar-field full" style="flex-direction:row;justify-content:space-between;margin-top:var(--ar-space-3);">';
    html += '<button type="button" class="ar-btn ar-btn-ghost" id="quiz-back">' + esc(t('← Zurück', '← Back')) + '</button>';
    html += '<button type="submit" class="ar-btn ar-btn-coral">' + esc(t('Ergebnis anzeigen →', 'Show my result →')) + '</button>';
    html += '</div>';
    html += '<p class="ar-small full" id="quiz-error" style="color:var(--ar-coral);display:none;"></p>';
    html += '</form>';
    stage.innerHTML = html;

    document.getElementById('quiz-back').addEventListener('click', function () { step -= 1; render(); });
    document.getElementById('quiz-lead').addEventListener('submit', function (e) {
      e.preventDefault();
      submit(new FormData(e.target));
    });
  }

  function submit(fd) {
    if (submitting) return;
    submitting = true;
    var err = document.getElementById('quiz-error');
    fetch('/api/quiz/' + encodeURIComponent(slug) + '/submit', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        answers: answers,
        email: fd.get('email'),
        name: fd.get('name') || null,
        company: fd.get('company') || null,
        consent: fd.get('consent') === 'on',
        lang: lang()
      })
    }).then(function (r) {
      if (!r.ok) throw new Error('submit failed');
      return r.json();
    }).then(function (data) {
      window.location.href = data.redirect;
    }).catch(function () {
      submitting = false;
      if (err) {
        err.textContent = t('Etwas ist schiefgelaufen. Bitte erneut versuchen.',
                            'Something went wrong. Please try again.');
        err.style.display = 'block';
      }
    });
  }

  window.addEventListener('langchange', function () { render(); });

  fetch('/api/quiz/' + encodeURIComponent(slug))
    .then(function (r) { return r.json(); })
    .then(function (data) { quiz = data; step = 0; render(); })
    .catch(function () {
      stage.innerHTML = '<p class="ar-mono">// ' +
        esc(t('Quiz konnte nicht geladen werden.', 'Could not load the quiz.')) + '</p>';
    });
})();
