/* Publish page: collect the form, POST it with the pasted bearer token, show
 * the returned cichéto YAML and offer it as a download. Vanilla, old-JS
 * friendly for WebPositive (XMLHttpRequest, no fetch/Promise). */
(function () {
  "use strict";

  var form = document.getElementById("publish-form");
  if (!form) return;

  // Translated messages from data-* on #js-msgs (English fallback).
  var MSGS = document.getElementById("js-msgs");
  function M(name, fallback) {
    return (MSGS && MSGS.getAttribute("data-m-" + name)) || fallback;
  }

  // Prefill the token from the stored login, if any (no manual paste needed).
  if (window.spritzAuth && window.spritzAuth.getToken()) {
    document.getElementById("token").value = window.spritzAuth.getToken();
  }

  // --- image upload helpers (convenience: returns a spritz-served URL) ---
  function uploadImage(kind, fileInput, statusEl, onUrl) {
    var token = (document.getElementById("token").value || "").trim();
    if (!token) { alert(M("needtoken", "Paste your access token first (step 1).")); return; }
    var f = fileInput.files && fileInput.files[0];
    if (!f) { alert(M("needfile", "Choose an image file first.")); return; }

    var fd = new FormData();
    fd.append("file", f);
    statusEl.textContent = M("uploading", "Uploading...");

    var xhr = new XMLHttpRequest();
    xhr.open("POST", "/upload/image?kind=" + encodeURIComponent(kind), true);
    xhr.setRequestHeader("Authorization", "Bearer " + token);
    xhr.onreadystatechange = function () {
      if (xhr.readyState !== 4) return;
      if (xhr.status === 200) {
        var url = JSON.parse(xhr.responseText).url;
        statusEl.textContent = M("uploaded", "Uploaded:") + " " + url;
        onUrl(url);
      } else if (xhr.status === 401) {
        statusEl.textContent = "";
        alert(M("badtoken", "Invalid or expired token."));
      } else {
        statusEl.textContent = "";
        alert(M("uploadfailed", "Upload failed") + " (" + xhr.status + "): "
              + extractDetail(xhr.responseText));
      }
    };
    xhr.send(fd);
  }

  var iconBtn = document.getElementById("icon-upload");
  if (iconBtn) iconBtn.onclick = function () {
    uploadImage("icon", document.getElementById("icon-file"),
                document.getElementById("icon-status"), function (url) {
      form.elements["icon"].value = url;
    });
  };

  var shotBtn = document.getElementById("shot-upload");
  if (shotBtn) shotBtn.onclick = function () {
    uploadImage("screenshot", document.getElementById("shot-file"),
                document.getElementById("shot-status"), function (url) {
      var ta = form.elements["screenshots"];
      ta.value = (ta.value ? ta.value.replace(/\s+$/, "") + "\n" : "") + url;
    });
  };

  form.onsubmit = function (e) {
    e.preventDefault();

    var token = (document.getElementById("token").value || "").trim();
    if (!token) {
      alert(M("needtoken", "Paste your access token first (step 1)."));
      return false;
    }

    // Collect fields into a plain object.
    var body = {};
    var els = form.elements;
    for (var i = 0; i < els.length; i++) {
      var el = els[i];
      if (el.name) body[el.name] = el.value;
    }

    var xhr = new XMLHttpRequest();
    xhr.open("POST", "/publish", true);
    xhr.setRequestHeader("Content-Type", "application/json");
    xhr.setRequestHeader("Authorization", "Bearer " + token);
    xhr.onreadystatechange = function () {
      if (xhr.readyState !== 4) return;
      if (xhr.status === 200) {
        showResult(xhr.responseText, body.id || "app");
      } else if (xhr.status === 401) {
        alert(M("badtokenrelogin", "Invalid or expired token. Log in again and paste the token."));
      } else if (xhr.status === 422) {
        alert(M("badcicheto", "Invalid cicheto:") + "\n\n" + extractDetail(xhr.responseText));
      } else if (xhr.status === 429) {
        alert(M("throttled", "Too many requests, try again shortly."));
      } else {
        alert(M("error", "Error") + " (" + xhr.status + "): " + xhr.responseText);
      }
    };
    xhr.send(JSON.stringify(body));
    return false;
  };

  function extractDetail(text) {
    try {
      var j = JSON.parse(text);
      return j.detail || text;
    } catch (e) {
      return text;
    }
  }

  function showResult(yamlText, id) {
    document.getElementById("result-yaml").textContent = yamlText;
    document.getElementById("result-name").textContent = id + ".yaml";
    var dl = document.getElementById("result-download");
    // data: URL so the download works without another round trip.
    dl.href = "data:application/x-yaml;charset=utf-8," +
      encodeURIComponent(yamlText);
    dl.setAttribute("download", id + ".yaml");
    document.getElementById("result").style.display = "block";
    document.getElementById("result").scrollIntoView();
  }
})();
