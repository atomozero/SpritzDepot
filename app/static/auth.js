/* Shared client-side auth: stores the JWT in localStorage and exposes helpers.
 * Vanilla, old-JS friendly for WebPositive. Loaded on every page (base.html).
 *
 * The token is a bearer JWT from /auth/login or /auth/register; we keep it in
 * localStorage and attach it to authenticated calls. No cookies. */
window.spritzAuth = (function () {
  "use strict";
  var KEY = "spritz_token";
  var EMAIL = "spritz_email";

  function getToken() { try { return localStorage.getItem(KEY) || ""; } catch (e) { return ""; } }
  function getEmail() { try { return localStorage.getItem(EMAIL) || ""; } catch (e) { return ""; } }
  function setToken(t, email) {
    try { localStorage.setItem(KEY, t); if (email) localStorage.setItem(EMAIL, email); } catch (e) {}
  }
  function clear() { try { localStorage.removeItem(KEY); localStorage.removeItem(EMAIL); } catch (e) {} }
  function isLoggedIn() { return !!getToken(); }

  // Decode the JWT payload (base64url middle segment) to read the "adm" claim.
  // This is UI-only: it decides whether to SHOW the admin link, never whether to
  // allow anything. Every admin action is re-authorized on the server. A tampered
  // token that flips "adm" gets a login link nowhere and 401 on every action.
  function isAdmin() {
    var t = getToken();
    if (!t) return false;
    try {
      var part = t.split(".")[1];
      if (!part) return false;
      part = part.replace(/-/g, "+").replace(/_/g, "/");
      while (part.length % 4) part += "=";
      var payload = JSON.parse(atob(part));
      return payload && payload.adm === true;
    } catch (e) { return false; }
  }

  function authHeader() {
    var t = getToken();
    return t ? { Authorization: "Bearer " + t } : {};
  }

  // Reflect login state in the header (set up by base.html).
  function refreshHeader() {
    var login = document.getElementById("nav-login");
    var logout = document.getElementById("nav-logout");
    var account = document.getElementById("nav-account");
    var admin = document.getElementById("nav-admin");
    if (!login || !logout) return;
    if (isLoggedIn()) {
      login.style.display = "none";
      logout.style.display = "";
      if (account) account.style.display = "";
      if (admin) admin.style.display = isAdmin() ? "" : "none";
    } else {
      login.style.display = "";
      logout.style.display = "none";
      if (account) account.style.display = "none";
      if (admin) admin.style.display = "none";
    }
  }

  function wireHeader() {
    var logout = document.getElementById("nav-logout");
    if (logout) logout.onclick = function (e) {
      e.preventDefault();
      // Real server-side logout: revoke the token, then drop the local copy.
      // Fire-and-forget; we clear and redirect regardless of the response so the
      // UI logs out even offline (the token also expires on its own).
      var t = getToken();
      if (t) {
        try {
          var xhr = new XMLHttpRequest();
          xhr.open("POST", "/auth/logout", true);
          xhr.setRequestHeader("Authorization", "Bearer " + t);
          xhr.send();
        } catch (err) {}
      }
      clear();
      refreshHeader();
      window.location.href = "/";
    };
    refreshHeader();
  }

  if (document.addEventListener) {
    document.addEventListener("DOMContentLoaded", wireHeader);
  }

  return {
    getToken: getToken, getEmail: getEmail, setToken: setToken,
    clear: clear, isLoggedIn: isLoggedIn, isAdmin: isAdmin,
    authHeader: authHeader, refreshHeader: refreshHeader
  };
})();
