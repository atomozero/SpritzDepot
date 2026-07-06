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
        // Match the <img>'s pixel box so layout does not shift.
        var size = parseInt(img.getAttribute("width"), 10) || 64;
        var svg = globalThis.HaikonSvg.renderIcon(data, size);
        // Carry over the class so existing CSS (.app-icon, .app-icon-sm) applies.
        if (img.className) svg.setAttribute("class", img.className);
        svg.setAttribute("width", size);
        svg.setAttribute("height", size);
        if (img.parentNode) img.parentNode.replaceChild(svg, img);
      } catch (e) {
        /* leave the original <img> (PNG or placeholder) in place */
      }
    };
    xhr.send();
  }

  function run() {
    var imgs = document.querySelectorAll("img[data-hvif]");
    for (var i = 0; i < imgs.length; i++) upgrade(imgs[i]);
  }

  if (document.addEventListener) {
    document.addEventListener("DOMContentLoaded", run);
  } else {
    run();
  }
})();
