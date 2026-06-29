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

  function authHeader() {
    var t = getToken();
    return t ? { Authorization: "Bearer " + t } : {};
  }

  // Reflect login state in the header (set up by base.html).
  function refreshHeader() {
    var login = document.getElementById("nav-login");
    var logout = document.getElementById("nav-logout");
    var who = document.getElementById("nav-who");
    if (!login || !logout) return;
    if (isLoggedIn()) {
      login.style.display = "none";
      logout.style.display = "";
      if (who) { who.style.display = ""; who.textContent = getEmail() || "loggato"; }
    } else {
      login.style.display = "";
      logout.style.display = "none";
      if (who) who.style.display = "none";
    }
  }

  function wireHeader() {
    var logout = document.getElementById("nav-logout");
    if (logout) logout.onclick = function (e) {
      e.preventDefault();
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
    clear: clear, isLoggedIn: isLoggedIn, authHeader: authHeader,
    refreshHeader: refreshHeader
  };
})();
