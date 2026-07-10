/* Admin statistics page: fetch /admin/stats and fill the tables. The page is a
 * shell; the admin gate lives on the endpoint. Same auth pattern as admin.js
 * (pasted X-Admin-Token, or the logged-in admin's bearer). Vanilla, old-JS
 * friendly (WebPositive). Values are inserted as text nodes, never innerHTML. */
(function () {
  "use strict";
  if (!document.getElementById("stats-btn")) return;

  var MSGS = document.getElementById("js-msgs");
  function M(name, fallback) {
    return (MSGS && MSGS.getAttribute("data-m-" + name)) || fallback;
  }

  function token() {
    return (document.getElementById("admin-token").value || "").trim();
  }
  function userToken() {
    return (window.spritzAuth && window.spritzAuth.getToken()) || "";
  }

  var status = document.getElementById("stats-status");

  function load() {
    if (!token() && !userToken()) {
      alert(M("need", "Log in as admin, or paste the admin token."));
      return;
    }
    status.textContent = M("loading", "Loading...");
    var xhr = new XMLHttpRequest();
    xhr.open("GET", "/admin/stats", true);
    if (token()) xhr.setRequestHeader("X-Admin-Token", token());
    if (userToken()) xhr.setRequestHeader("Authorization", "Bearer " + userToken());
    xhr.onreadystatechange = function () {
      if (xhr.readyState !== 4) return;
      if (xhr.status >= 200 && xhr.status < 300) {
        status.textContent = "";
        fill(JSON.parse(xhr.responseText));
        document.getElementById("stats-body").style.display = "block";
        return;
      }
      status.textContent = "";
      if (xhr.status === 401) alert(M("badtoken", "Invalid admin token."));
      else if (xhr.status === 503) alert(M("disabled", "Admin endpoint disabled."));
      else alert(M("error", "Error") + " (" + xhr.status + ")");
    };
    xhr.send(null);
  }

  document.getElementById("stats-btn").onclick = load;

  function set(id, value) {
    var el = document.getElementById(id);
    if (el) el.textContent = (value == null ? "-" : String(value));
  }

  /* "resolve 380 · installed 96", or a dash when the map is empty. */
  function pairs(obj) {
    var out = [], k;
    for (k in obj) {
      if (obj.hasOwnProperty(k)) out.push(k + " " + obj[k]);
    }
    return out.length ? out.join(" · ") : "-";
  }

  function cell(text) {
    var td = document.createElement("td");
    td.appendChild(document.createTextNode(text == null ? "" : String(text)));
    return td;
  }

  /* Show `table` filled from `rows` via rowEl, or `empty` when there are none. */
  function table(tableId, bodyId, emptyId, rows, rowEl) {
    var t = document.getElementById(tableId);
    var body = document.getElementById(bodyId);
    var empty = document.getElementById(emptyId);
    body.innerHTML = "";
    if (!rows || rows.length === 0) {
      t.style.display = "none";
      empty.style.display = "block";
      return;
    }
    empty.style.display = "none";
    t.style.display = "table";
    for (var i = 0; i < rows.length; i++) body.appendChild(rowEl(rows[i]));
  }

  function stamp(iso) {
    return iso ? iso.replace("T", " ").slice(0, 19) : "";
  }

  function fill(d) {
    var cat = d.catalog || {};
    set("s-cicheti", cat.cicheti);
    set("s-bacari", cat.bacari);
    set("s-bridge", cat.with_haikuports_bridge);

    var u = d.users || {};
    set("s-users", u.total);
    set("s-admins", u.admins);
    set("s-users30", u.last_30d);

    var lib = d.library || {};
    set("s-pending", lib.pending);
    set("s-installed", lib.installed);
    set("s-removed", lib.removed);

    var dl = d.downloads || {};
    set("s-dl-total", dl.total);
    set("s-dl-alltime", dl.all_time);
    set("s-dl-kind", pairs(dl.by_kind || {}));
    set("s-dl-channel", pairs(dl.by_channel || {}));
    set("s-dl-arch", pairs(dl.by_arch || {}));

    table("s-top-table", "s-top-body", "s-top-empty", dl.top || [], function (r) {
      var tr = document.createElement("tr");
      tr.appendChild(cell(r.name));
      tr.appendChild(cell(r.id));
      tr.appendChild(cell(r.downloads));
      return tr;
    });

    var bac = d.bacari || {};
    set("s-bacari-summary",
        (bac.total || 0) + " · " + (bac.failing || 0) + " " + M("errors", "errors"));
    table("s-bacari-table", "s-bacari-body", "s-bacari-empty", bac.rows || [], function (r) {
      var tr = document.createElement("tr");
      tr.appendChild(cell(r.slug));
      tr.appendChild(cell(stamp(r.last_ingested_at)));
      tr.appendChild(cell(r.last_ingested));
      tr.appendChild(cell(r.last_error || ""));
      return tr;
    });

    var om = d.ombra || {};
    set("s-ombra-summary",
        (om.ok || 0) + " " + M("ok", "ok") + " · "
        + (om.errors || 0) + " " + M("errors", "errors"));
    table("s-ombra-table", "s-ombra-body", "s-ombra-empty", om.failing || [], function (r) {
      var tr = document.createElement("tr");
      tr.appendChild(cell(r.id));
      tr.appendChild(cell(r.repo));
      tr.appendChild(cell(r.error));
      return tr;
    });
  }
})();
