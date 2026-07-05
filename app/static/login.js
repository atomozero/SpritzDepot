/* Login page: call /auth/login or /auth/register, store the JWT via spritzAuth,
 * then go to "my apps". Vanilla, old-JS friendly. */
(function () {
  "use strict";
  var form = document.getElementById("auth-form");
  if (!form) return;
  var status = document.getElementById("auth-status");
  // Translated messages come from the template via data-* (English fallback).
  function msg(name, fallback) {
    return form.getAttribute("data-msg-" + name) || fallback;
  }

  function submit(path) {
    var email = form.elements["email"].value.trim();
    var password = form.elements["password"].value;
    if (!email || !password) { alert(msg("required", "Email and password are required.")); return; }
    status.textContent = msg("wait", "Please wait...");

    var xhr = new XMLHttpRequest();
    xhr.open("POST", path, true);
    xhr.setRequestHeader("Content-Type", "application/json");
    xhr.onreadystatechange = function () {
      if (xhr.readyState !== 4) return;
      if (xhr.status === 200) {
        var tok = JSON.parse(xhr.responseText).access_token;
        window.spritzAuth.setToken(tok, email);
        status.textContent = msg("done", "Done.");
        window.location.href = "/library-page";
      } else if (xhr.status === 401) {
        status.textContent = "";
        alert(msg("wrong", "Wrong email or password."));
      } else if (xhr.status === 409) {
        status.textContent = "";
        alert(msg("exists", "This email is already registered. Try logging in."));
      } else if (xhr.status === 422) {
        status.textContent = "";
        alert(msg("short", "Password too short."));
      } else if (xhr.status === 429) {
        status.textContent = "";
        alert(msg("throttled", "Too many attempts, try again shortly."));
      } else {
        status.textContent = "";
        alert(msg("error", "Error") + " (" + xhr.status + ").");
      }
    };
    xhr.send(JSON.stringify({ email: email, password: password }));
  }

  form.onsubmit = function (e) { e.preventDefault(); submit("/auth/login"); };
  document.getElementById("btn-register").onclick = function () { submit("/auth/register"); };
})();
