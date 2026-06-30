/* Admin page: ingest / re-crawl taps and rebuild repos. Every call carries the
 * pasted admin token as X-Admin-Token. Vanilla, old-JS friendly. */
(function () {
  "use strict";
  if (!document.getElementById("ing-btn")) return;

  function token() {
    return (document.getElementById("admin-token").value || "").trim();
  }
  function need() {
    if (!token()) { alert("Incolla prima il token admin."); return false; }
    return true;
  }

  function req(method, url, onok, opts) {
    opts = opts || {};
    var xhr = new XMLHttpRequest();
    xhr.open(method, url, true);
    xhr.setRequestHeader("X-Admin-Token", token());
    if (opts.json) xhr.setRequestHeader("Content-Type", "application/json");
    xhr.onreadystatechange = function () {
      if (xhr.readyState !== 4) return;
      if (xhr.status >= 200 && xhr.status < 300) {
        onok(xhr.responseText ? JSON.parse(xhr.responseText) : null);
      } else if (xhr.status === 401) {
        alert("Token admin non valido.");
      } else if (xhr.status === 503) {
        alert("Endpoint admin disabilitato (SPRITZ_ADMIN_TOKEN non configurato).");
      } else {
        alert("Errore (" + xhr.status + "): " + (xhr.responseText || ""));
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
    if (!url || !slug) { alert("URL e slug sono obbligatori."); return; }
    statusEl.textContent = "Ingest in corso...";
    req("POST", "/ingest", function (data) {
      statusEl.textContent = "Fatto.";
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
    if (!url || !slug) { alert("URL e slug sono obbligatori."); return; }
    var statusEl = document.getElementById("imp-status");
    var resultEl = document.getElementById("imp-result");
    statusEl.textContent = "Import in corso (puo' richiedere qualche secondo)...";
    req("POST", "/repo/import-hpkr", function (data) {
      var n = data.ingested ? data.ingested.length : 0;
      var found = data.found_in_catalog != null ? data.found_in_catalog : n;
      statusEl.textContent = "Importati " + n + " di " + found + " pacchetti.";
      resultEl.style.display = "block";
      resultEl.textContent = JSON.stringify(data, null, 2);
      loadBacari();
    }, { json: true, body: JSON.stringify({ repo_url: url, bacaro: slug }) });
  };

  document.getElementById("rebuild-btn").onclick = function () {
    if (!need()) return;
    var s = document.getElementById("admin-status");
    s.textContent = "Rebuild in corso...";
    req("POST", "/repo/build", function (data) {
      s.textContent = "Rebuild: " + (data.built ? data.built.length : 0) +
        " repo, " + (data.errors ? data.errors.length : 0) + " errori.";
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
    btn.textContent = "Ri-crawl";
    btn.onclick = function () {
      ingest(r.git_url, r.slug, document.getElementById("admin-status"), null);
    };
    if (!r.git_url) { btn.disabled = true; btn.title = "URL non memorizzato"; }
    td.appendChild(btn);

    var del = document.createElement("button");
    del.className = "btn btn-danger";
    del.textContent = "Elimina";
    del.style.marginLeft = "6px";
    del.onclick = function () {
      if (!confirm("Eliminare il bacaro '" + r.slug + "' e tutte le sue app dal "
                   + "catalogo? Il repo originale non viene toccato.")) return;
      var s = document.getElementById("admin-status");
      s.textContent = "Eliminazione...";
      req("DELETE", "/bacari/" + encodeURIComponent(r.slug), function (data) {
        s.textContent = "Eliminato '" + data.deleted_bacaro + "' ("
          + data.removed_cicheti + " app rimosse).";
        loadBacari();
      });
    };
    td.appendChild(del);
    tr.appendChild(td);
    if (r.last_error) {
      tr.title = "Ultimo errore: " + r.last_error;
    }
    return tr;
  }
})();
