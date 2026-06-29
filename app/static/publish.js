/* Publish page: collect the form, POST it with the pasted bearer token, show
 * the returned cichéto YAML and offer it as a download. Vanilla, old-JS
 * friendly for WebPositive (XMLHttpRequest, no fetch/Promise). */
(function () {
  "use strict";

  var form = document.getElementById("publish-form");
  if (!form) return;

  form.onsubmit = function (e) {
    e.preventDefault();

    var token = (document.getElementById("token").value || "").trim();
    if (!token) {
      alert("Incolla prima il tuo token di accesso (punto 1).");
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
        alert("Token non valido o scaduto. Rifai il login e incolla il token.");
      } else if (xhr.status === 422) {
        alert("Cicheto non valido:\n\n" + extractDetail(xhr.responseText));
      } else if (xhr.status === 429) {
        alert("Troppe richieste, riprova tra poco.");
      } else {
        alert("Errore (" + xhr.status + "): " + xhr.responseText);
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
