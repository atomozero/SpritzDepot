/* "My data" page (GDPR): export via /auth/me, erasure via /auth/delete-account.
 * Vanilla, old-JS friendly for WebPositive (XMLHttpRequest, no fetch). */
(function () {
  "use strict";

  var root = document.getElementById("export-btn");
  if (!root) return;
  var page = document.querySelector(".app-detail");
  function M(name, fallback) {
    return (page && page.getAttribute("data-m-" + name)) || fallback;
  }
  function token() {
    return (window.spritzAuth && window.spritzAuth.getToken()) || "";
  }

  // --- export (access + portability) ---
  document.getElementById("export-btn").onclick = function (e) {
    e.preventDefault();
    var t = token();
    if (!t) { alert(M("needlogin", "Log in to see your data.")); return; }
    var xhr = new XMLHttpRequest();
    xhr.open("GET", "/auth/me", true);
    xhr.setRequestHeader("Authorization", "Bearer " + t);
    xhr.onreadystatechange = function () {
      if (xhr.readyState !== 4) return;
      if (xhr.status === 200) {
        var out = document.getElementById("export-out");
        out.style.display = "block";
        out.textContent = JSON.stringify(JSON.parse(xhr.responseText), null, 2);
      } else if (xhr.status === 401) {
        alert(M("needlogin", "Log in to see your data."));
      } else {
        alert(M("error", "Error") + " (" + xhr.status + ").");
      }
    };
    xhr.send();
  };

  // --- erasure ---
  document.getElementById("delete-form").onsubmit = function (e) {
    e.preventDefault();
    var t = token();
    if (!t) { alert(M("needlogin", "Log in to see your data.")); return false; }
    var pw = this.elements["password"].value;
    var status = document.getElementById("delete-status");
    var xhr = new XMLHttpRequest();
    xhr.open("POST", "/auth/delete-account", true);
    xhr.setRequestHeader("Content-Type", "application/json");
    xhr.setRequestHeader("Authorization", "Bearer " + t);
    xhr.onreadystatechange = function () {
      if (xhr.readyState !== 4) return;
      if (xhr.status === 200) {
        if (window.spritzAuth) window.spritzAuth.clear();
        alert(M("deleted", "Account deleted. Goodbye."));
        window.location.href = "/";
      } else if (xhr.status === 401) {
        status.textContent = "";
        alert(M("wrongpw", "Wrong password."));
      } else {
        status.textContent = "";
        alert(M("error", "Error") + " (" + xhr.status + ").");
      }
    };
    xhr.send(JSON.stringify({ password: pw }));
    return false;
  };
})();
