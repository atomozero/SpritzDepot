/* Degrading install button.
 *
 * Default markup already shows the fallback (add-repo / get-spritz). If the
 * native spritz client is running it exposes a small local HTTP endpoint
 * (the "Pippo pattern"); when that answers, we prepend a one-click
 * spritz:// deep link to each channel's actions.
 *
 * Kept tiny and old-JS friendly for WebPositive: no fetch/Promise required,
 * XMLHttpRequest with a short timeout. Mixed-content (https page calling
 * http://localhost) just fails the probe and we stay on the fallback, which is
 * the safe, correct degradation.
 */
(function () {
  "use strict";

  // Where the native client is expected to answer locally.
  var PROBE_URL = "http://127.0.0.1:4242/ping";
  var PROBE_TIMEOUT_MS = 800;

  function onClientDetected() {
    var channels = document.querySelectorAll(".channel");
    for (var i = 0; i < channels.length; i++) {
      var ch = channels[i];
      var cicheto = ch.getAttribute("data-cicheto");
      var channel = ch.getAttribute("data-channel");
      var actions = ch.querySelector(".install-actions");
      if (!actions || !cicheto) continue;

      var link = document.createElement("a");
      link.className = "btn btn-deeplink";
      link.href = "spritz://install/" + encodeURIComponent(cicheto) +
        "?channel=" + encodeURIComponent(channel);
      // Label is translated in the template and passed via data-deeplink-label,
      // with an English fallback if the attribute is missing.
      link.textContent = ch.getAttribute("data-deeplink-label") ||
        "Install with one click (spritz client)";
      // Put the one-click action first.
      actions.insertBefore(link, actions.firstChild);
    }
  }

  function probe() {
    var done = false;
    var xhr = new XMLHttpRequest();
    var timer = setTimeout(function () {
      if (done) return;
      done = true;
      try { xhr.abort(); } catch (e) {}
      // No client: leave the fallback as is.
    }, PROBE_TIMEOUT_MS);

    xhr.onreadystatechange = function () {
      if (xhr.readyState !== 4 || done) return;
      done = true;
      clearTimeout(timer);
      if (xhr.status >= 200 && xhr.status < 300) {
        onClientDetected();
      }
    };
    try {
      xhr.open("GET", PROBE_URL, true);
      xhr.timeout = PROBE_TIMEOUT_MS;
      xhr.send();
    } catch (e) {
      // Mixed content or blocked: stay on the fallback.
      clearTimeout(timer);
    }
  }

  probe();
})();
