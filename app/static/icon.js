/* Client-side app icons: render each app's raw HVIF blob to crisp SVG in the
 * browser (via haikon_full.js), so no server-side hvif2png is needed.
 *
 * Progressive enhancement: every icon <img> already has a working src (/icon PNG
 * with an onerror -> placeholder fallback). This script only UPGRADES an <img>
 * that carries data-hvif="<id>": it fetches /hvif/<id>, renders the SVG, and
 * swaps it in. Any failure (no HVIF, parser missing, old engine) leaves the
 * original <img> untouched, so nothing ever ends up broken.
 *
 * Vanilla + XHR; verified to run on WebPositive 1.3.
 */
(function () {
  "use strict";

  // Need both the parser and the SVG renderer; if the vendored script did not
  // load or run, leave every <img> as-is (PNG/placeholder still works).
  if (typeof globalThis === "undefined" ||
      !globalThis.Haikon || !globalThis.HaikonSvg) {
    return;
  }

  function upgrade(img) {
    var id = img.getAttribute("data-hvif");
    if (!id) return;

    var xhr = new XMLHttpRequest();
    xhr.open("GET", "/hvif/" + encodeURIComponent(id), true);
    xhr.responseType = "arraybuffer";
    xhr.onreadystatechange = function () {
      if (xhr.readyState !== 4) return;
      if (xhr.status !== 200 || !xhr.response) return;   // keep the <img> fallback
      try {
        var buf = new Uint8Array(xhr.response);
        var data = globalThis.Haikon.parse(buf);
        var wrapper = globalThis.HaikonSvg.renderIcon(data, 64);
        // renderIcon returns a <span> wrapping the <svg>; we want the <svg>
        // itself so it inherits the icon's CSS box (.featured-icon, .app-icon-sm,
        // ...) instead of the wrapper collapsing.
        var svg = wrapper && wrapper.tagName && wrapper.tagName.toLowerCase() === "svg"
          ? wrapper
          : (wrapper.querySelector ? wrapper.querySelector("svg") : null);
        if (!svg) return;  // unexpected shape: keep the <img> fallback
        // The renderer hard-codes style="width:2em;height:2em", which makes the
        // icon tiny. Drop it and size the svg to the exact box the <img> occupied
        // so nothing shifts, whether the size comes from CSS (.featured-icon,
        // .app-icon-sm) or from the <img>'s width attribute (the app page).
        svg.removeAttribute("style");
        if (img.className) svg.setAttribute("class", img.className);
        var box = img.getBoundingClientRect();
        var w = Math.round(box.width) ||
                parseInt(img.getAttribute("width"), 10) || 64;
        var h = Math.round(box.height) ||
                parseInt(img.getAttribute("height"), 10) || w;
        svg.setAttribute("width", w);
        svg.setAttribute("height", h);
        if (img.parentNode) img.parentNode.replaceChild(svg, img);
      } catch (e) {
        /* leave the original <img> (PNG or placeholder) in place */
      }
    };
    xhr.send();
  }

  function run() {
    // Only upgrade images not yet processed (mark them so a re-run is cheap and
    // idempotent when called again after new cards are injected).
    var imgs = document.querySelectorAll("img[data-hvif]");
    for (var i = 0; i < imgs.length; i++) {
      var img = imgs[i];
      if (img.getAttribute("data-hvif-done")) continue;
      img.setAttribute("data-hvif-done", "1");
      upgrade(img);
    }
  }

  // Expose run() so code that injects icons later (the library list, built by XHR
  // after DOMContentLoaded) can trigger the HVIF -> SVG upgrade on its new cards.
  window.spritzIcons = { run: run };

  if (document.addEventListener) {
    document.addEventListener("DOMContentLoaded", run);
  } else {
    run();
  }
})();
