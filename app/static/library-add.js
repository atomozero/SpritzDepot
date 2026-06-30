/* "Add to library" button on the app page. Queues the app for install via
 * POST /library/{id} using the logged-in user's token. If not logged in, it
 * sends the user to /login. Vanilla, old-JS friendly. */
(function () {
  "use strict";
  var box = document.getElementById("library-box");
  var btn = document.getElementById("lib-add");
  if (!box || !btn) return;

  var cicheto = box.getAttribute("data-cicheto");
  var status = document.getElementById("lib-status");

  // Messages injected by the template via data-* so they can be translated.
  var MSG = {
    login: box.getAttribute("data-msg-login") || "Accedi per aggiungere alla libreria.",
    added: box.getAttribute("data-msg-added") || "Aggiunta alla libreria.",
    error: box.getAttribute("data-msg-error") || "Errore."
  };

  btn.onclick = function () {
    var tok = window.spritzAuth && window.spritzAuth.getToken();
    if (!tok) {
      status.textContent = MSG.login;
      window.location.href = "/login";
      return;
    }
    btn.disabled = true;
    status.textContent = "...";
    var xhr = new XMLHttpRequest();
    xhr.open("POST", "/library/" + encodeURIComponent(cicheto), true);
    xhr.setRequestHeader("Content-Type", "application/json");
    xhr.setRequestHeader("Authorization", "Bearer " + tok);
    xhr.onreadystatechange = function () {
      if (xhr.readyState !== 4) return;
      btn.disabled = false;
      if (xhr.status >= 200 && xhr.status < 300) {
        status.textContent = MSG.added;
        btn.style.display = "none";
      } else if (xhr.status === 401) {
        status.textContent = MSG.login;
        window.location.href = "/login";
      } else {
        status.textContent = MSG.error + " (" + xhr.status + ")";
      }
    };
    // channel defaults to stable server-side; arch optional
    xhr.send(JSON.stringify({ channel: "stable" }));
  };
})();
