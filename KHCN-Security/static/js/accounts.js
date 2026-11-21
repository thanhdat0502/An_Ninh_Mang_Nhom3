"use strict";

(() => {
  if (!document.querySelector("[data-account-workspace]")) return;
  const api = window.KHCNAuth;
  const ui = window.KHCNUI;
  const form = document.querySelector("[data-account-filter]");
  const editor = document.querySelector("[data-account-editor]");
  const dialog = document.querySelector("[data-account-dialog]");
  const rows = document.querySelector("[data-account-rows]");
  const message = document.querySelector("[data-account-message]");
  let currentPage = 1;
  let requestId = 0;
  let selected = null;
  let loadingEditor = false;

  function tell(text, success = false) {
    message.textContent = text;
    message.className = `alert ${success ? "alert-success" : "alert-danger"}`;
    message.hidden = !text;
  }

  async function get(url, options) {
    const response = await api.request(url, options);
    const data = await response.json();
    if (!response.ok) {
      if (response.status === 401) document.querySelector("[data-account-login]").hidden = false;
      const error = new Error(response.status === 401 ? "Vui lòng đăng nhập để tiếp tục."
        : response.status === 403 ? "Bạn không có quyền quản lý tài khoản này hoặc yêu cầu không hợp lệ."
          : response.status === 400 ? "Thông tin chưa hợp lệ. Kiểm tra các trường được đánh dấu."
            : "Không thể tải hoặc cập nhật tài khoản. Vui lòng thử lại.");
      error.fields = response.status === 400 ? data : {};
      error.status = response.status;
      throw error;
    }
    return data;
  }

  async function load(page = 1) {
    const sequence = ++requestId;
    const button = form.querySelector('[type="submit"]');
    ui.busy(button, true, "Đang tìm…");
    rows.setAttribute("aria-busy", "true");
    ui.tableState(rows, 5, "Đang tải tài khoản…", "", true);
    const query = new URLSearchParams(new FormData(form));
    query.set("page", String(page));
    query.set("page_size", "12");
    try {
      const data = await get(`/api/accounts/?${query}`);
      if (sequence !== requestId) return;
      currentPage = page;
      rows.replaceChildren();
      for (const account of data.results) {
        const row = rows.insertRow();
        row.dataset.accountId = String(account.id);
        row.insertCell().textContent = `#${account.id}`;
        const name = row.insertCell();
        name.textContent = account.full_name;
        const email = document.createElement("small");
        email.textContent = account.email;
        name.append(email);
        const roleCell = row.insertCell();
        const roleList = document.createElement("div");
        roleList.className = "account-role-list";
        roleCell.append(roleList);
        if (!account.roles.length) roleList.textContent = "Chưa có vai trò";
        for (const role of account.roles) {
          const label = document.createElement("span");
          label.textContent = ui.roles[role] || role;
          roleList.append(label);
        }
        row.insertCell().append(ui.badge(account.is_active ? "ACTIVE" : "INACTIVE", account.is_active ? "Đang hoạt động" : "Đã khóa"));
        const actions = row.insertCell();
        if (account.can_edit) {
          const edit = document.createElement("button");
          edit.type = "button";
          edit.className = "workspace-action";
          edit.textContent = "Chỉnh sửa";
          edit.setAttribute("aria-label", `Chỉnh sửa tài khoản ${account.full_name}`);
          edit.addEventListener("click", () => openEditor(account.id, edit));
          actions.append(edit);
        } else actions.textContent = "Chỉ xem";
      }
      if (!data.results.length) ui.tableState(rows, 5, "Không tìm thấy tài khoản", "Thử tên, email hoặc bộ lọc khác.");
      document.querySelector("[data-account-count]").textContent = `${data.count} tài khoản`;
      document.querySelector("[data-account-page]").textContent = `Trang ${page}`;
      document.querySelector("[data-account-prev]").disabled = !data.previous;
      document.querySelector("[data-account-next]").disabled = !data.next;
    } catch (error) {
      if (sequence !== requestId) return;
      if (error.status === 404 && page > 1) return load(1);
      ui.tableState(rows, 5, "Chưa tải được danh sách", "Tải lại trang hoặc thử tìm kiếm lại.");
      tell(error.message);
    } finally {
      if (sequence === requestId) {
        ui.busy(button, false);
        rows.removeAttribute("aria-busy");
      }
    }
  }

  async function openEditor(id, button) {
    if (loadingEditor) return;
    loadingEditor = true;
    ui.busy(button, true);
    try {
      selected = await get(`/api/accounts/${id}/`);
      editor.reset();
      ui.clearErrors(editor, "[data-account-editor-message]");
      editor.elements.full_name.value = selected.full_name;
      editor.elements.email.value = selected.email;
      editor.elements.is_active.value = String(selected.is_active);
      document.querySelector("[data-account-editor-role]").textContent = selected.roles.map(role => ui.roles[role]).join(", ") || "Chưa có vai trò";
      dialog.showModal();
      editor.elements.full_name.focus();
    } catch (error) { tell(error.message); }
    finally { ui.busy(button, false); loadingEditor = false; }
  }

  async function save(event) {
    event.preventDefault();
    if (!selected) return;
    const changes = { full_name: editor.elements.full_name.value, email: editor.elements.email.value, is_active: editor.elements.is_active.value === "true" };
    ui.clearErrors(editor, "[data-account-editor-message]");
    const button = editor.querySelector('[type="submit"]');
    ui.busy(button, true, "Đang lưu…");
    try {
      if (changes.is_active !== selected.is_active) {
        const accepted = await ui.confirm({
          title: changes.is_active ? "Mở lại tài khoản?" : "Khóa tài khoản?",
          description: changes.is_active ? `Cho phép ${selected.full_name} tiếp tục đăng nhập hệ thống.` : `${selected.full_name} sẽ không thể đăng nhập hoặc tiếp tục gọi API khi tài khoản bị khóa.`,
          action: changes.is_active ? "Mở tài khoản" : "Khóa tài khoản", danger: !changes.is_active,
        });
        if (!accepted) return;
      }
      await get(`/api/accounts/${selected.id}/`, { method: "PATCH", data: changes });
      dialog.close();
      await load(currentPage);
      tell("Đã cập nhật tài khoản.", true);
    } catch (error) {
      let first = null;
      for (const [name, messages] of Object.entries(error.fields || {})) {
        const field = editor.elements.namedItem(name);
        const hint = document.getElementById(`account-error-${name}`);
        if (!field || !hint) continue;
        hint.textContent = Array.isArray(messages) ? messages.join(" ") : String(messages);
        hint.hidden = false;
        field.setAttribute("aria-invalid", "true");
        first ||= field;
      }
      const hint = editor.querySelector("[data-account-editor-message]");
      hint.textContent = error.message;
      hint.hidden = false;
      first?.focus();
    } finally { ui.busy(button, false); }
  }

  form.addEventListener("submit", event => { event.preventDefault(); tell(""); load(1); });
  editor.addEventListener("submit", save);
  document.querySelector("[data-account-close]").addEventListener("click", () => dialog.close());
  document.querySelector("[data-account-cancel]").addEventListener("click", () => dialog.close());
  document.querySelector("[data-account-prev]").addEventListener("click", () => load(currentPage - 1));
  document.querySelector("[data-account-next]").addEventListener("click", () => load(currentPage + 1));
  async function showPermissionManagement() {
    // Reuse the existing server capability and native Groups administration.
    // A JWT business admin without staff permission keeps this link hidden.
    try {
      const response = await api.request("/api/topics/capabilities/");
      if (!response.ok) return;
      const capabilities = await response.json();
      if (!capabilities.account_management_url) return;
      const target = new URL(capabilities.account_management_url, location.origin);
      if (target.origin !== location.origin || !target.pathname.startsWith("/admin/")) return;
      const link = document.querySelector("[data-account-permissions]");
      link.href = target.href;
      link.hidden = false;
    } catch {
      // Optional navigation fails closed; the account API reports its own errors.
      document.querySelector("[data-account-permissions]").hidden = true;
    }
  }

  get("/api/accounts/capabilities/").then(() => {
    document.querySelector("[data-account-content]").hidden = false;
    showPermissionManagement();
    return load();
  }).catch(error => tell(error.message));
})();
