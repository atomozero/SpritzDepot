/* "My apps" page: fetch /library with the stored login token and render the
 * list. The token lives in the login (spritzAuth), not a field on this page;
 * managing it moved to "My data". Vanilla, old-JS friendly (XMLHttpRequest). */
(function () {
  "use strict";

  // Labels/messages come from data-* on #result so they can be translated.
  var R = document.getElementById("result");
  if (!R) return;
  var STATE_LABEL = {
    pending: (R && R.getAttribute("data-s-pending")) || "in coda",
    installed: (R && R.getAttribute("data-s-installed")) || "installata",
    removed: (R && R.getAttribute("data-s-removed")) || "rimossa"
  };
  var REMOVE_LABEL = (R && R.getAttribute("data-s-remove")) || "Rimuovi";
  function M(name, fallback) {
    return (R && R.getAttribute("data-msg-" + name)) || fallback;
  }

  function token() {
    return (window.spritzAuth && window.spritzAuth.getToken()) || "";
  }

  function load() {
    var tok = token();
    if (!tok) {
      // Not logged in on this address: show the login prompt, hide the list.
      var need = document.getElementById("need-login");
      if (need) need.style.display = "block";
      R.style.display = "none";
      return;
    }
    var xhr = new XMLHttpRequest();
    xhr.open("GET", "/library", true);
    xhr.setRequestHeader("Authorization", "Bearer " + tok);
    xhr.onreadystatechange = function () {
      if (xhr.readyState !== 4) return;
      if (xhr.status === 200) {
        render(JSON.parse(xhr.responseText));
      } else if (xhr.status === 401) {
        // Token gone/expired: fall back to the login prompt.
        var need = document.getElementById("need-login");
        if (need) need.style.display = "block";
        R.style.display = "none";
      } else {
        alert(M("error", "Error") + " (" + xhr.status + ").");
      }
    };
    xhr.send();
  }

  // Load automatically on open.
  load();

  function render(items) {
    var list = document.getElementById("lib-list");
    var empty = document.getElementById("lib-empty");
    list.innerHTML = "";
    var need = document.getElementById("need-login");
    if (need) need.style.display = "none";
    document.getElementById("result").style.display = "block";

    if (!items || items.length === 0) {
      empty.style.display = "block";
      return;
    }
    empty.style.display = "none";

    for (var i = 0; i < items.length; i++) {
      var it = items[i];
      var li = document.createElement("li");
      li.className = "app-card lib-card";

      // Icon + name, laid out like the catalog cards. The icon is the /icon PNG
      // with an onerror -> placeholder, plus data-hvif so icon.js can upgrade it
      // to a crisp SVG client-side (same as the catalog).
      var a = document.createElement("a");
      a.className = "app-link app-link-row";
      a.href = "/app/" + encodeURIComponent(it.cicheto);

      var img = document.createElement("img");
      img.className = "app-icon-sm";
      img.setAttribute("alt", "");
      img.setAttribute("data-hvif", it.cicheto);
      // Set onerror BEFORE src: assigning src starts the load immediately, and a
      // fast 404 (e.g. an app with no extractable icon) could fire before a
      // later-assigned handler, leaving a broken image. Handler first, src last.
      (function (name) {
        img.onerror = function () {
          img.onerror = null;
          img.src = "/placeholder.svg?name=" + encodeURIComponent(name);
        };
      })(it.name || it.cicheto);
      img.src = "/icon/" + encodeURIComponent(it.cicheto);
      a.appendChild(img);

      var txt = document.createElement("span");
      txt.className = "app-link-text";
      var nm = document.createElement("span");
      nm.className = "app-name";
      nm.appendChild(document.createTextNode(it.name || it.cicheto));
      txt.appendChild(nm);
      a.appendChild(txt);
      li.appendChild(a);

      // Meta: channel + a state pill with its own colour, then the remove button
      // on its own line so it does not crowd the badges.
      var meta = document.createElement("div");
      meta.className = "app-meta";
      meta.appendChild(badge("badge-channel", it.channel));
      if (it.arch) meta.appendChild(badge("badge", it.arch));
      meta.appendChild(badge("badge-state badge-state-" + it.state,
                             STATE_LABEL[it.state] || it.state));
      li.appendChild(meta);

      var actions = document.createElement("div");
      actions.className = "lib-actions";
      var rm = document.createElement("button");
      rm.className = "btn btn-fallback btn-remove";
      rm.textContent = REMOVE_LABEL;
      rm.onclick = (function (cid) {
        return function () { removeFromLibrary(cid); };
      })(it.cicheto);
      actions.appendChild(rm);
      li.appendChild(actions);

      list.appendChild(li);
    }
    // These cards were injected after DOMContentLoaded, so icon.js has not seen
    // them yet: trigger the HVIF -> SVG upgrade on the new icons.
    if (window.spritzIcons) window.spritzIcons.run();
  }

  function removeFromLibrary(cid) {
    var tok = token();
    if (!tok) return;
    var xhr = new XMLHttpRequest();
    xhr.open("POST", "/library/" + encodeURIComponent(cid) + "/remove", true);
    xhr.setRequestHeader("Authorization", "Bearer " + tok);
    xhr.onreadystatechange = function () {
      if (xhr.readyState !== 4) return;
      if (xhr.status >= 200 && xhr.status < 300) {
        load();  // reload the list
      } else if (xhr.status === 401) {
        alert(M("expired", "Session expired, log in again."));
      }
    };
    xhr.send();
  }

  function badge(cls, text) {
    var s = document.createElement("span");
    s.className = "badge " + cls;
    s.appendChild(document.createTextNode(text));
    return s;
  }
})();
