(function () {
  "use strict";

  var state = { products: [], editingId: null };

  function $(selector) { return document.querySelector(selector); }

  function showBanner(message, kind) {
    var el = $("#banner");
    el.textContent = message || "";
    el.className = "banner " + (kind || "");
    el.hidden = !message;
  }

  function money(value) {
    return Number(value || 0).toLocaleString(undefined, {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2
    });
  }

  function request(path, options) {
    return fetch(path, options || {}).then(function (response) {
      return response.text().then(function (text) {
        var body = null;
        if (text) { try { body = JSON.parse(text); } catch (err) { body = null; } }
        if (!response.ok) {
          var message = body && body.error && body.error.message
            ? body.error.message : ("HTTP " + response.status);
          if (body && body.error && body.error.fields) {
            message += " — " + Object.keys(body.error.fields).map(function (field) {
              return field + ": " + body.error.fields[field];
            }).join(", ");
          }
          throw new Error(message);
        }
        return body || {};
      });
    });
  }

  // ── rendering ────────────────────────────────────────────────────────

  function renderDashboard(stats) {
    $("#kpi-products").textContent = String(stats.product_count);
    $("#kpi-value").textContent = money(stats.total_value);
    $("#kpi-units").textContent = String(stats.total_units);
    $("#kpi-low").textContent = String(stats.low_stock_count);
    var card = $("#kpi-low-card");
    if (stats.low_stock_count > 0) { card.classList.add("alert"); }
    else { card.classList.remove("alert"); }
  }

  function statusTag(product) {
    var span = document.createElement("span");
    if (product.quantity === 0) {
      span.className = "tag out";
      span.textContent = "Out";
    } else if (product.low_stock) {
      span.className = "tag low";
      span.textContent = "Low";
    } else {
      span.className = "tag ok";
      span.textContent = "OK";
    }
    return span;
  }

  function renderProducts(products) {
    var body = document.querySelector("#products tbody");
    var empty = $("#empty");
    body.textContent = "";
    state.products = products;
    if (!products.length) {
      empty.hidden = false;
      return;
    }
    empty.hidden = true;

    products.forEach(function (product) {
      var row = document.createElement("tr");
      if (product.low_stock) { row.className = "low"; row.dataset.lowStock = "1"; }
      row.dataset.id = String(product.id);

      function cell(text, className) {
        var td = document.createElement("td");
        if (className) { td.className = className; }
        td.textContent = text;
        row.appendChild(td);
      }
      cell(product.name);
      cell(product.category);
      cell(String(product.quantity), "num");
      cell(money(product.unit_price), "num");
      cell(String(product.reorder_level), "num");
      cell(money(product.inventory_value), "num");

      var statusCell = document.createElement("td");
      statusCell.appendChild(statusTag(product));
      row.appendChild(statusCell);

      var actions = document.createElement("td");
      actions.className = "row-actions";
      var edit = document.createElement("button");
      edit.type = "button";
      edit.textContent = "Edit";
      edit.addEventListener("click", function () { startEdit(product); });
      var remove = document.createElement("button");
      remove.type = "button";
      remove.textContent = "Delete";
      remove.className = "danger";
      remove.addEventListener("click", function () { removeProduct(product); });
      actions.appendChild(edit);
      actions.appendChild(remove);
      row.appendChild(actions);

      body.appendChild(row);
    });

    renderProductOptions(products);
  }

  function renderProductOptions(products) {
    var select = $("#m-product");
    var previous = select.value;
    select.textContent = "";
    products.forEach(function (product) {
      var option = document.createElement("option");
      option.value = String(product.id);
      option.textContent = product.name + " (" + product.quantity + ")";
      select.appendChild(option);
    });
    if (previous) { select.value = previous; }
  }

  function renderCategories(categories) {
    var select = $("#category");
    var current = select.value;
    select.textContent = "";
    var all = document.createElement("option");
    all.value = "";
    all.textContent = "All categories";
    select.appendChild(all);

    var list = $("#category-list");
    list.textContent = "";
    categories.forEach(function (category) {
      var option = document.createElement("option");
      option.value = category;
      option.textContent = category;
      select.appendChild(option);

      var suggestion = document.createElement("option");
      suggestion.value = category;
      list.appendChild(suggestion);
    });
    select.value = current;
  }

  function renderMovements(items) {
    var host = $("#movements");
    host.textContent = "";
    if (!items.length) {
      var empty = document.createElement("li");
      empty.textContent = "No movements recorded yet.";
      host.appendChild(empty);
      return;
    }
    items.slice(0, 12).forEach(function (item) {
      var li = document.createElement("li");
      var strong = document.createElement("strong");
      strong.textContent = (item.quantity_change > 0 ? "+" : "") + item.quantity_change;
      li.appendChild(strong);
      li.appendChild(document.createTextNode(
        " · " + item.movement_type + " · " + (item.reason || "no reason") +
        " · " + item.created_at));
      host.appendChild(li);
    });
  }

  // ── data ─────────────────────────────────────────────────────────────

  function currentQuery() {
    var params = [];
    var search = $("#search").value.trim();
    var category = $("#category").value;
    if (search) { params.push("search=" + encodeURIComponent(search)); }
    if (category) { params.push("category=" + encodeURIComponent(category)); }
    return params.length ? "?" + params.join("&") : "";
  }

  function loadProducts() {
    return request("/api/products" + currentQuery()).then(function (payload) {
      renderProducts(payload.products || []);
    });
  }

  function loadDashboard() {
    return request("/api/dashboard").then(renderDashboard);
  }

  function loadCategories() {
    return request("/api/categories").then(function (payload) {
      renderCategories(payload.categories || []);
    });
  }

  function reload() {
    return Promise.all([loadDashboard(), loadProducts()])
      .catch(function (err) {
        showBanner("Could not load the inventory: " + err.message, "error");
      });
  }

  // ── form ─────────────────────────────────────────────────────────────

  function readForm() {
    return {
      name: $("#f-name").value,
      category: $("#f-category").value,
      quantity: Number($("#f-quantity").value || 0),
      unit_price: Number($("#f-price").value || 0),
      reorder_level: Number($("#f-reorder").value || 0)
    };
  }

  function resetForm() {
    state.editingId = null;
    $("#product-form").reset();
    $("#f-quantity").value = "0";
    $("#f-reorder").value = "0";
    $("#form-title").textContent = "Add product";
    $("#save").textContent = "Add product";
    $("#cancel-edit").hidden = true;
    $("#form-error").hidden = true;
  }

  function startEdit(product) {
    state.editingId = product.id;
    $("#f-name").value = product.name;
    $("#f-category").value = product.category;
    $("#f-quantity").value = String(product.quantity);
    $("#f-price").value = String(product.unit_price);
    $("#f-reorder").value = String(product.reorder_level);
    $("#form-title").textContent = "Edit product #" + product.id;
    $("#save").textContent = "Save changes";
    $("#cancel-edit").hidden = false;
    $("#form-error").hidden = true;
    $("#f-name").focus();
  }

  function submitProduct(event) {
    event.preventDefault();
    var payload = readForm();
    var editingId = state.editingId;
    var options = {
      method: editingId ? "PUT" : "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    };
    var path = editingId ? "/api/products/" + editingId : "/api/products";

    request(path, options).then(function (result) {
      var name = result.product ? result.product.name : payload.name;
      showBanner((editingId ? "Saved " : "Added ") + name, "ok");
      resetForm();
      return reload();
    }).catch(function (err) {
      $("#form-error").textContent = err.message;
      $("#form-error").hidden = false;
      showBanner("Save failed: " + err.message, "error");
    });
  }

  function removeProduct(product) {
    if (!window.confirm("Delete " + product.name + "?")) { return; }
    request("/api/products/" + product.id, { method: "DELETE" }).then(function () {
      showBanner("Deleted " + product.name, "ok");
      if (state.editingId === product.id) { resetForm(); }
      return reload();
    }).catch(function (err) {
      showBanner("Delete failed: " + err.message, "error");
    });
  }

  function submitMovement(event) {
    event.preventDefault();
    var productId = $("#m-product").value;
    if (!productId) {
      showBanner("Add a product before recording a movement.", "error");
      return;
    }
    var payload = {
      movement_type: $("#m-type").value,
      quantity_change: Number($("#m-change").value || 0),
      reason: $("#m-reason").value
    };
    request("/api/products/" + productId + "/movements", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    }).then(function (result) {
      var movement = result.movement || {};
      showBanner("Recorded " + movement.quantity_change + " (now " +
        movement.quantity_after + " in stock)", "ok");
      $("#m-reason").value = "";
      return reload().then(function () { return loadMovements(productId); });
    }).catch(function (err) {
      showBanner("Movement rejected: " + err.message, "error");
    });
  }

  function loadMovements(productId) {
    var id = productId || $("#m-product").value;
    if (!id) { return Promise.resolve(); }
    return request("/api/products/" + id + "/movements").then(function (payload) {
      renderMovements(payload.movements || []);
    });
  }

  // ── wiring ───────────────────────────────────────────────────────────

  function bind() {
    $("#search").addEventListener("input", function () {
      loadProducts().catch(function (err) {
        showBanner("Search failed: " + err.message, "error");
      });
    });
    $("#category").addEventListener("change", function () {
      loadProducts().catch(function (err) {
        showBanner("Filter failed: " + err.message, "error");
      });
    });
    $("#reset-filters").addEventListener("click", function () {
      $("#search").value = "";
      $("#category").value = "";
      loadProducts();
    });
    $("#product-form").addEventListener("submit", submitProduct);
    $("#cancel-edit").addEventListener("click", resetForm);
    $("#movement-form").addEventListener("submit", submitMovement);
    $("#m-product").addEventListener("change", function () {
      loadMovements($("#m-product").value);
    });

    Promise.all([loadCategories(), loadDashboard(), loadProducts()])
      .then(function () { return loadMovements(); })
      .catch(function (err) {
        showBanner("Could not load the inventory: " + err.message, "error");
      });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", bind);
  } else {
    bind();
  }
})();
