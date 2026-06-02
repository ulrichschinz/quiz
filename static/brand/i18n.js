/* Agentic Reach — i18n
 * Usage:
 *   ARi18n.register({ de: { hello: 'Hallo' }, en: { hello: 'Hi' } });
 *   ARi18n.apply('de');                        // initial
 *   <span data-i18n="hello">Hallo</span>       // gets replaced
 *   <button data-lang-btn="de">DE</button>     // auto-wired
 */
(function () {
  const dicts = { de: {}, en: {} };
  let current = 'de';

  function register(translations) {
    for (const lang of Object.keys(translations)) {
      dicts[lang] = Object.assign(dicts[lang] || {}, translations[lang]);
    }
  }

  function apply(lang) {
    if (!dicts[lang]) return;
    current = lang;
    document.body.dataset.lang = lang;
    document.documentElement.lang = lang;
    const dict = dicts[lang];
    document.querySelectorAll('[data-i18n]').forEach((el) => {
      const key = el.dataset.i18n;
      if (dict[key] != null) el.innerHTML = dict[key];
    });
    document.querySelectorAll('[data-lang-btn]').forEach((b) => {
      b.classList.toggle('active', b.dataset.langBtn === lang);
    });
  }

  function init(defaultLang) {
    document.querySelectorAll('[data-lang-btn]').forEach((b) => {
      b.addEventListener('click', () => apply(b.dataset.langBtn));
    });
    apply(defaultLang || document.body.dataset.lang || 'de');
  }

  window.ARi18n = { register, apply, init, get current() { return current; } };
})();
