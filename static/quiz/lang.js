/* Unified DE/EN toggle. Mirrors the landing page (public/lang.js): the URL
 * parameter ?lang=de|en is the source of truth, so a quiz page can be linked
 * or shared in a given language. Every [data-de]/[data-en] element swaps its
 * content, the choice is remembered, internal links keep carrying ?lang=,
 * and a 'langchange' event lets the quiz player re-render its questions.
 * Admin pages hide the DE/EN toggle and stay German — there the URL and links
 * are left untouched.
 *
 * Security (SEC-014/015): served as an external file so the CSP needs no
 * inline script. The data-<lang> values are admin-editable text, so they are
 * NEVER assigned via innerHTML: renderInline() builds DOM nodes and honours
 * only the inline allowlist <em>, <strong>, <br> (same as the server-side
 * `inline_html` Jinja filter, app/shared/safe_html.py). Anything else —
 * <img onerror=…>, <script>, attributes — is shown as literal text.
 */
(function () {
  var VALID = ['de', 'en'];
  var STORAGE_KEY = 'ar_lang'; // shared key/convention with the landing page
  // Bare allowlisted tags only (no attributes): <em> </em> <strong> </strong> <br> <br/>
  var TAG_RE = /<(\/?)(em|strong|br)\s*\/?>/gi;

  function isValid(l) { return VALID.indexOf(l) !== -1; }

  function renderInline(el, text) {
    var frag = document.createDocumentFragment();
    var stack = [frag];
    var last = 0;
    var m;
    TAG_RE.lastIndex = 0;
    function top() { return stack[stack.length - 1]; }
    function pushText(s) { if (s) top().appendChild(document.createTextNode(s)); }
    while ((m = TAG_RE.exec(text)) !== null) {
      pushText(text.slice(last, m.index));
      last = TAG_RE.lastIndex;
      var closing = m[1] === '/';
      var tag = m[2].toLowerCase();
      if (tag === 'br') {
        if (!closing) top().appendChild(document.createElement('br'));
      } else if (!closing) {
        var node = document.createElement(tag);
        top().appendChild(node);
        stack.push(node);
      } else if (stack.length > 1 && top().nodeName.toLowerCase() === tag) {
        stack.pop();
      }
    }
    pushText(text.slice(last));
    el.textContent = '';
    el.appendChild(frag);
  }

  // ?lang= → remembered choice → browser language → server-rendered default.
  function detectInitial() {
    var urlLang = new URLSearchParams(location.search).get('lang');
    if (isValid(urlLang)) return urlLang;
    var stored = null;
    try { stored = localStorage.getItem(STORAGE_KEY); } catch (e) {}
    if (isValid(stored)) return stored;
    var nav = (navigator.language || '').slice(0, 2).toLowerCase();
    if (nav === 'en') return 'en';
    return document.body.dataset.lang === 'en' ? 'en' : 'de';
  }

  // Only public pages offer language switching (they render the DE/EN toggle).
  function addressable() { return !!document.querySelector('[data-lang-btn]'); }

  function syncUrl(lang) {
    var p = new URLSearchParams(location.search);
    if (p.get('lang') === lang) return;
    p.set('lang', lang);
    history.replaceState(null, '', location.pathname + '?' + p.toString() + location.hash);
  }

  // Append ?lang=<active> to an internal href so navigation keeps the language.
  // External schemes (http/mailto/tel/…) and pure anchors (#foo) stay as-is.
  function withLang(href, lang) {
    if (!href) return href;
    if (/^(https?:|mailto:|tel:|javascript:|data:)/i.test(href)) return href;
    if (href.charAt(0) === '#') return href;
    var hashIdx = href.indexOf('#');
    var hash = hashIdx >= 0 ? href.slice(hashIdx) : '';
    var noHash = hashIdx >= 0 ? href.slice(0, hashIdx) : href;
    var qIdx = noHash.indexOf('?');
    var path = qIdx >= 0 ? noHash.slice(0, qIdx) : noHash;
    var params = new URLSearchParams(qIdx >= 0 ? noHash.slice(qIdx + 1) : '');
    params.set('lang', lang);
    return path + '?' + params.toString() + hash;
  }

  function rewriteLinks(lang) {
    document.querySelectorAll('a[href]').forEach(function (a) {
      if (a.hasAttribute('data-no-lang')) return;
      a.setAttribute('href', withLang(a.getAttribute('href'), lang));
    });
  }

  function setLang(lang) {
    if (!isValid(lang)) lang = 'de';
    document.body.dataset.lang = lang;
    document.documentElement.lang = lang;
    document.querySelectorAll('[data-' + lang + ']').forEach(function (el) {
      var v = el.getAttribute('data-' + lang);
      if (v != null) renderInline(el, v);
    });
    document.querySelectorAll('[data-lang-btn]').forEach(function (b) {
      b.classList.toggle('active', b.dataset.langBtn === lang);
    });
    try { localStorage.setItem(STORAGE_KEY, lang); } catch (e) {}
    if (addressable()) { syncUrl(lang); rewriteLinks(lang); }
    window.dispatchEvent(new CustomEvent('langchange', { detail: { lang: lang } }));
  }

  window.ARQuizLang = { set: setLang, get: function () { return document.body.dataset.lang || 'de'; } };

  function init() {
    document.querySelectorAll('[data-lang-btn]').forEach(function (b) {
      b.addEventListener('click', function () { setLang(b.dataset.langBtn); });
    });
    setLang(detectInitial());
  }
  // This file is loaded with `defer`: it runs before DOMContentLoaded, and so do
  // later deferred scripts (player.js), which must have registered their
  // 'langchange' listener before the first setLang — so always wait for it.
  document.addEventListener('DOMContentLoaded', init);
})();
