/* Featured carousel on the home hero.
 *
 * Adaptive to the UI profile (body class ui-lite / ui-modern):
 *   - modern: the track scrolls fluidly (CSS scroll-snap); the arrows nudge it
 *     by two cards using scrollTo/scrollBy, smoothly where supported.
 *   - lite (WebPositive): no scroll-snap, so we PAGINATE. Cards are shown two at
 *     a time and the arrows step through the pages by toggling display.
 *
 * Vanilla + old-JS friendly. With <= the page size of cards, the arrows hide.
 */
(function () {
  "use strict";

  var PER_PAGE = 2;  // "a due a due"

  function isLite() {
    var b = document.body;
    return b && b.className && b.className.indexOf("ui-lite") !== -1;
  }

  function setup(carousel) {
    var track = carousel.querySelector(".featured-track");
    if (!track) return;
    var cards = track.querySelectorAll(".featured-card");
    var prev = carousel.querySelector(".featured-prev");
    var next = carousel.querySelector(".featured-next");
    if (!cards.length) return;

    // One page (or fewer cards than a page): nothing to scroll, hide the arrows.
    if (cards.length <= PER_PAGE) {
      if (prev) prev.style.display = "none";
      if (next) next.style.display = "none";
      return;
    }

    if (isLite()) {
      setupPaged(cards, prev, next);
    } else {
      setupScroll(track, cards, prev, next);
    }
  }

  // --- lite: show PER_PAGE cards, arrows step pages by toggling display ---
  function setupPaged(cards, prev, next) {
    var pages = Math.ceil(cards.length / PER_PAGE);
    var page = 0;

    function render() {
      for (var i = 0; i < cards.length; i++) {
        var onPage = (i >= page * PER_PAGE) && (i < (page + 1) * PER_PAGE);
        cards[i].style.display = onPage ? "" : "none";
      }
      if (prev) prev.disabled = (page === 0);
      if (next) next.disabled = (page === pages - 1);
    }
    if (prev) prev.onclick = function () { if (page > 0) { page--; render(); } };
    if (next) next.onclick = function () { if (page < pages - 1) { page++; render(); } };
    render();
  }

  // --- modern: scroll the track by two card widths ---
  function setupScroll(track, cards, prev, next) {
    function step() {
      // width of PER_PAGE cards plus the gap between them.
      var card = cards[0];
      var w = card.getBoundingClientRect().width;
      return (w + 18) * PER_PAGE;   // 18px matches the track gap in CSS
    }
    function go(dir) {
      var amount = step() * dir;
      if (track.scrollBy) {
        try { track.scrollBy({ left: amount, behavior: "smooth" }); return; }
        catch (e) { /* fall through */ }
      }
      track.scrollLeft += amount;
    }
    if (prev) prev.onclick = function () { go(-1); };
    if (next) next.onclick = function () { go(1); };
  }

  function run() {
    var carousels = document.querySelectorAll("[data-featured-carousel]");
    for (var i = 0; i < carousels.length; i++) setup(carousels[i]);
  }

  if (document.addEventListener) {
    document.addEventListener("DOMContentLoaded", run);
  } else {
    run();
  }
})();
