/* "My apps" page: fetch /library with the pasted bearer token and render the
 * list. Vanilla, old-JS friendly for WebPositive (XMLHttpRequest). */
(function () {
  "use strict";

  var btn = document.getElementById("load");
  if (!btn) return;

  var STATE_LABEL = {
    pending: "in coda",
    installed: "installata",
    removed: "rimossa"
  };

  // Prefill the token field from the stored login, if any.
  if (window.spritzAuth && window.spritzAuth.getToken()) {
    document.getElementById("token").value = window.spritzAuth.getToken();
  }

  btn.onclick = function () {
    var token = (document.getElementById("token").value || "").trim() ||
                (window.spritzAuth ? window.spritzAuth.getToken() : "");
    if (!token) { alert("Accedi prima (link Accedi in alto)."); return; }

    var xhr = new XMLHttpRequest();
    xhr.open("GET", "/library", true);
    xhr.setRequestHeader("Authorization", "Bearer " + token);
    xhr.onreadystatechange = function () {
      if (xhr.readyState !== 4) return;
      if (xhr.status === 200) {
        render(JSON.parse(xhr.responseText));
      } else if (xhr.status === 401) {
        alert("Token non valido o scaduto.");
      } else {
        alert("Errore (" + xhr.status + ").");
      }
    };
    xhr.send();
  };

  // If already logged in, load automatically on open.
  if (window.spritzAuth && window.spritzAuth.getToken()) {
    btn.click();
  }

  function render(items) {
    var list = document.getElementById("lib-list");
    var empty = document.getElementById("lib-empty");
    list.innerHTML = "";
    document.getElementById("result").style.display = "block";

    if (!items || items.length === 0) {
      empty.style.display = "block";
      return;
    }
    empty.style.display = "none";

    for (var i = 0; i < items.length; i++) {
      var it = items[i];
      var li = document.createElement("li");
      li.className = "app-card";

      var a = document.createElement("a");
      a.className = "app-link";
      a.href = "/app/" + encodeURIComponent(it.cicheto);
      var nm = document.createElement("span");
      nm.className = "app-name";
      nm.appendChild(document.createTextNode(it.name || it.cicheto));
      a.appendChild(nm);
      li.appendChild(a);

      var meta = document.createElement("div");
      meta.className = "app-meta";
      meta.appendChild(badge("badge-channel", it.channel));
      if (it.arch) meta.appendChild(badge("badge", it.arch));
      meta.appendChild(badge("badge-bridge", STATE_LABEL[it.state] || it.state));
      li.appendChild(meta);

      list.appendChild(li);
    }
  }

  function badge(cls, text) {
    var s = document.createElement("span");
    s.className = "badge " + cls;
    s.appendChild(document.createTextNode(text));
    return s;
  }
})();
