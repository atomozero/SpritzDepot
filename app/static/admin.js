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
    tr.appendChild(td);
    if (r.last_error) {
      tr.title = "Ultimo errore: " + r.last_error;
    }
    return tr;
  }
})();
