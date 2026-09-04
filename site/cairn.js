/* Cairn — site behaviour. Two small things, no dependencies.
 *
 * 1. A theme toggle. The default is the OS preference (no data-theme attribute
 *    at all), and a click pins light or dark. Stored per-browser, wrapped in
 *    try/catch because a browser set to block site data throws on access
 *    rather than returning null.
 * 2. Active-section highlighting in the sticky table of contents on the long
 *    reference pages. IntersectionObserver, so it costs nothing while idle.
 */
(function () {
  'use strict';

  var root = document.documentElement;

  function stored(key) {
    try { return localStorage.getItem(key); } catch (e) { return null; }
  }
  function store(key, value) {
    try { localStorage.setItem(key, value); } catch (e) { /* nothing to do */ }
  }

  var saved = stored('cairn-theme');
  if (saved === 'light' || saved === 'dark') root.setAttribute('data-theme', saved);

  function currentlyDark() {
    var pinned = root.getAttribute('data-theme');
    if (pinned) return pinned === 'dark';
    return window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
  }

  var toggle = document.getElementById('theme');
  if (toggle) {
    var label = function () { toggle.textContent = currentlyDark() ? 'light' : 'dark'; };
    label();
    toggle.addEventListener('click', function () {
      var next = currentlyDark() ? 'light' : 'dark';
      root.setAttribute('data-theme', next);
      store('cairn-theme', next);
      label();
    });
  }

  /* ---- table of contents ------------------------------------------------ */

  var toc = document.querySelector('.toc');
  if (!toc || !('IntersectionObserver' in window)) return;

  var links = {};
  Array.prototype.forEach.call(toc.querySelectorAll('a[href^="#"]'), function (a) {
    links[a.getAttribute('href').slice(1)] = a;
  });

  var targets = Object.keys(links)
    .map(function (id) { return document.getElementById(id); })
    .filter(Boolean);
  if (!targets.length) return;

  var visible = {};

  function paint() {
    /* The topmost visible section wins, so scrolling up and down through a page
       gives the same answer at the same scroll position. */
    var best = null;
    targets.forEach(function (el) {
      if (visible[el.id] && (!best || el.offsetTop < best.offsetTop)) best = el;
    });
    Object.keys(links).forEach(function (id) {
      links[id].classList.toggle('active', !!best && id === best.id);
    });
  }

  var io = new IntersectionObserver(function (entries) {
    entries.forEach(function (e) { visible[e.target.id] = e.isIntersecting; });
    paint();
  }, { rootMargin: '-76px 0px -55% 0px' });

  targets.forEach(function (el) { io.observe(el); });
})();
