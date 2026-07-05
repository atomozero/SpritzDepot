/* Admin page: ingest / re-crawl taps and rebuild repos. Every call carries the
 * pasted admin token as X-Admin-Token. Vanilla, old-JS friendly. */
(function () {
  "use strict";
  if (!document.getElementById("ing-btn")) return;

  // Translated messages from data-* on #js-msgs (English fallback). Optional
  // {placeholders} in the string are filled from the vars object.
  var MSGS = document.getElementById("js-msgs");
  function M(name, fallback, vars) {
    var s = (MSGS && MSGS.getAttribute("data-m-" + name)) || fallback;
    if (vars) {
      for (var k in vars) {
        if (vars.hasOwnProperty(k)) s = s.replace("{" + k + "}", vars[k]);
      }
    }
    return s;
  }

  function token() {
    return (document.getElementById("admin-token").value || "").trim();
  }
  function userToken() {
    return (window.spritzAuth && window.spritzAuth.getToken()) || "";
  }
  function need() {
    // Either an admin token in the field, or a logged-in (admin) user.
    if (!token() && !userToken()) {
      alert(M("need", "Log in as admin, or paste the admin token."));
      return false;
    }
    return true;
  }

  function req(method, url, onok, opts) {
    opts = opts || {};
    var xhr = new XMLHttpRequest();
    xhr.open(method, url, true);
    if (token()) xhr.setRequestHeader("X-Admin-Token", token());
    if (userToken()) xhr.setRequestHeader("Authorization", "Bearer " + userToken());
    if (opts.json) xhr.setRequestHeader("Content-Type", "application/json");
    xhr.onreadystatechange = function () {
      if (xhr.readyState !== 4) return;
      if (xhr.status >= 200 && xhr.status < 300) {
        onok(xhr.responseText ? JSON.parse(xhr.responseText) : null);
      } else if (xhr.status === 401) {
        alert(M("badtoken", "Invalid admin token."));
      } else if (xhr.status === 503) {
        alert(M("disabled", "Admin endpoint disabled (SPRITZ_ADMIN_TOKEN not set)."));
      } else {
        alert(M("error", "Error") + " (" + xhr.status + "): " + (xhr.responseText || ""));
      }
      // Clear any "in progress" status lines on a non-2xx outcome.
      if (xhr.status < 200 || xhr.status >= 300) {
        var s1 = document.getElementById("imp-status");
        var s2 = document.getElementById("ing-status");
        if (s1) s1.textContent = "";
        if (s2) s2.textContent = "";
      }
    };
    xhr.send(opts.body || null);
  }

  function ingest(url, slug, statusEl, resultEl) {
    if (!need()) return;
    if (!url || !slug) { alert(M("needurlslug", "URL and slug are required.")); return; }
    statusEl.textContent = M("ingesting", "Ingesting...");
    req("POST", "/ingest", function (data) {
      statusEl.textContent = M("done", "Done.");
      if (resultEl) {
        resultEl.style.display = "block";
        resultEl.textContent = JSON.stringify(data, null, 2);
      }
      loadBacari();
    }, { json: true, body: JSON.stringify({ git_url: url, bacaro: slug }) });
  }

  document.getElementById("ing-btn").onclick = function () {
    ingest(document.getElementById("ing-url").value.trim(),
           document.getElementById("ing-slug").value.trim(),
           document.getElementById("ing-status"),
           document.getElementById("ing-result"));
  };

  document.getElementById("imp-btn").onclick = function () {
    if (!need()) return;
    var url = document.getElementById("imp-url").value.trim();
    var slug = document.getElementById("imp-slug").value.trim();
    if (!url || !slug) { alert(M("needurlslug", "URL and slug are required.")); return; }
    var statusEl = document.getElementById("imp-status");
    var resultEl = document.getElementById("imp-result");
    statusEl.textContent = M("importing", "Importing (may take a few seconds)...");
    req("POST", "/repo/import-hpkr", function (data) {
      var n = data.ingested ? data.ingested.length : 0;
      var found = data.found_in_catalog != null ? data.found_in_catalog : n;
      statusEl.textContent = M("imported", "Imported {n} of {found} packages.",
                               { n: n, found: found });
      resultEl.style.display = "block";
      resultEl.textContent = JSON.stringify(data, null, 2);
      loadBacari();
    }, { json: true, body: JSON.stringify({ repo_url: url, bacaro: slug }) });
  };

  document.getElementById("rebuild-btn").onclick = function () {
    if (!need()) return;
    var s = document.getElementById("admin-status");
    s.textContent = M("rebuilding", "Rebuilding...");
    req("POST", "/repo/build", function (data) {
      s.textContent = M("rebuilt", "Rebuild: {n} repos, {e} errors.", {
        n: (data.built ? data.built.length : 0),
        e: (data.errors ? data.errors.length : 0)
      });
    });
  };

  document.getElementById("refresh-btn").onclick = loadBacari;

  function loadBacari() {
    if (!need()) return;
    req("GET", "/admin/bacari", render);
  }

  function render(rows) {
    var table = document.getElementById("bacari-table");
    var body = document.getElementById("bacari-body");
    var empty = document.getElementById("bacari-empty");
    body.innerHTML = "";
    if (!rows || rows.length === 0) {
      table.style.display = "none";
      empty.style.display = "block";
      return;
    }
    empty.style.display = "none";
    table.style.display = "table";
    for (var i = 0; i < rows.length; i++) {
      body.appendChild(rowEl(rows[i]));
    }
  }

  function cell(text) {
    var td = document.createElement("td");
    td.appendChild(document.createTextNode(text == null ? "" : String(text)));
    return td;
  }

  function rowEl(r) {
    var tr = document.createElement("tr");
    tr.appendChild(cell(r.slug));
    tr.appendChild(cell(r.git_url));
    tr.appendChild(cell(r.last_ingested_at ? r.last_ingested_at.replace("T", " ").slice(0, 19) : ""));
    tr.appendChild(cell(r.last_ingested));
    tr.appendChild(cell(r.last_removed));
    var td = document.createElement("td");
    var btn = document.createElement("button");
    btn.className = "btn btn-fallback";
    btn.textContent = M("recrawl", "Re-crawl");
    btn.onclick = function () {
      ingest(r.git_url, r.slug, document.getElementById("admin-status"), null);
    };
    if (!r.git_url) { btn.disabled = true; btn.title = M("nourl", "URL not stored"); }
    td.appendChild(btn);

    var del = document.createElement("button");
    del.className = "btn btn-danger";
    del.textContent = M("delete", "Delete");
    del.style.marginLeft = "6px";
    del.onclick = function () {
      if (!confirm(M("confirmdelete", "Delete bacaro '{slug}' and all its apps "
                   + "from the catalog?", { slug: r.slug }) + " "
                   + M("confirmdeletenote", "The original repo is untouched."))) return;
      var s = document.getElementById("admin-status");
      s.textContent = M("deleting", "Deleting...");
      req("DELETE", "/bacari/" + encodeURIComponent(r.slug), function (data) {
        s.textContent = M("deleted", "Deleted '{slug}' ({n} apps removed).",
          { slug: data.deleted_bacaro, n: data.removed_cicheti });
        loadBacari();
      });
    };
    td.appendChild(del);
    tr.appendChild(td);
    if (r.last_error) {
      tr.title = M("lasterror", "Last error:") + " " + r.last_error;
    }
    return tr;
  }
})();
