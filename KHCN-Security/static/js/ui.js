"use strict";

// Presentation helpers only. The API remains authoritative for all permissions.
window.KHCNUI = (() => {
  const roles = { ADMIN: "Quản trị viên", LECTURER: "Giảng viên", STUDENT: "Sinh viên" };
  const originals = new WeakMap();
  const sidebar = document.querySelector("#app-sidebar");
  const toggle = document.querySelector("[data-menu-toggle]");
  const closeMenu = document.querySelector("[data-menu-close]");

  function menu(open) {
    if (!sidebar || !toggle) return;
    sidebar.classList.toggle("is-open", open);
    toggle.setAttribute("aria-expanded", String(open));
    toggle.setAttribute("aria-label", open ? "Đóng điều hướng" : "Mở điều hướng");
    if (open) {
      sidebar.setAttribute("role", "dialog");
      sidebar.setAttribute("aria-modal", "true");
      document.querySelector(".app-main").inert = true;
      document.body.style.overflow = "hidden";
      closeMenu.focus();
    } else {
      sidebar.removeAttribute("role");
      sidebar.removeAttribute("aria-modal");
      document.querySelector(".app-main").inert = false;
      document.body.style.overflow = "";
      if (getComputedStyle(toggle).display !== "none") toggle.focus();
    }
  }
  toggle?.addEventListener("click", () => menu(!sidebar.classList.contains("is-open")));
  closeMenu?.addEventListener("click", () => menu(false));
  sidebar?.addEventListener("keydown", event => {
    if (!sidebar.classList.contains("is-open")) return;
    if (event.key === "Escape") { event.preventDefault(); menu(false); }
    if (event.key === "Tab") {
      const controls = [...sidebar.querySelectorAll("a[href],button")].filter(el => el.getClientRects().length);
      const first = controls[0];
      const last = controls[controls.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    }
  });
  matchMedia("(min-width: 992px)").addEventListener("change", event => {
    if (event.matches && sidebar?.classList.contains("is-open")) menu(false);
  });
  const route = location.pathname;
  const active = route.startsWith("/tong-quan/") ? "dashboard" : route.startsWith("/de-tai/") ? "topics"
    : route.startsWith("/dang-ky/") ? "registrations" : route.startsWith("/tai-khoan/") ? "accounts" : "catalog";
  document.querySelector(`[data-nav="${active}"]`)?.setAttribute("aria-current", "page");
  document.querySelectorAll('.table-responsive[role="region"]').forEach(region => {
    const hint = document.createElement("p");
    hint.className = "table-hint";
    hint.textContent = "Cuộn ngang để xem đầy đủ trạng thái và thao tác →";
    region.before(hint);
  });

  function badge(status, label) {
    const element = document.createElement("span");
    const safe = /^[A-Z_]+$/.test(String(status)) ? String(status).toLowerCase() : "unknown";
    element.className = `status-badge status-${safe}`;
    element.textContent = label;
    return element;
  }

  function tableState(rows, columns, title, description = "", loading = false) {
    rows.replaceChildren();
    const row = rows.insertRow();
    row.className = "table-state";
    const cell = row.insertCell();
    cell.colSpan = columns;
    const box = document.createElement("div");
    box.className = loading ? "loading-state" : "empty-state";
    if (loading) box.textContent = title;
    else {
      const heading = document.createElement("h3");
      heading.textContent = title;
      const detail = document.createElement("p");
      detail.textContent = description;
      box.append(heading, detail);
    }
    cell.append(box);
  }

  function busy(element, on, label = "Đang xử lý…") {
    if (!element) return;
    if (on && !originals.has(element)) {
      originals.set(element, [...element.childNodes].map(node => node.cloneNode(true)));
      element.replaceChildren(document.createTextNode(label));
    } else if (!on && originals.has(element)) {
      element.replaceChildren(...originals.get(element));
      originals.delete(element);
    }
    element.disabled = on;
    if (on) element.setAttribute("aria-busy", "true");
    else element.removeAttribute("aria-busy");
  }

  function confirm({ title, description, action = "Xác nhận", danger = false }) {
    const dialog = document.querySelector("[data-confirm-dialog]");
    if (!dialog || dialog.open) return Promise.resolve(false);
    dialog.querySelector("[data-confirm-title]").textContent = title;
    dialog.querySelector("[data-confirm-description]").textContent = description;
    const button = dialog.querySelector("[data-confirm-submit]");
    button.textContent = action;
    button.className = `btn ${danger ? "btn-danger" : "btn-primary"}`;
    dialog.returnValue = "cancel";
    return new Promise(resolve => {
      dialog.addEventListener("close", () => resolve(dialog.returnValue === "confirm"), { once: true });
      dialog.showModal();
    });
  }

  function clearErrors(form, messageSelector) {
    form.querySelectorAll(".field-error").forEach(element => { element.hidden = true; element.textContent = ""; });
    form.querySelectorAll("[aria-invalid]").forEach(element => element.removeAttribute("aria-invalid"));
    const message = form.querySelector(messageSelector);
    if (message) message.hidden = true;
  }

  return { roles, badge, tableState, busy, confirm, clearErrors };
})();
