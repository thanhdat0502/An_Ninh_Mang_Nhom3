"use strict";

(() => {
  const workspace = document.querySelector("[data-topic-workspace]");
  const detail = document.querySelector("[data-topic-detail]");
  if (!workspace && !detail) return;
  const api = window.KHCNAuth;
  const ui = window.KHCNUI;
  const message = document.querySelector("[data-topic-message]");
  const login = document.querySelector("[data-topic-login]");
  let capabilities = null;
  let currentPage = 1;
  let editingId = null;
  let listRequest = 0;
  let editorLoading = false;

  function tell(text) {
    message.textContent = text;
    message.hidden = !text;
  }

  async function fetchData(url, options) {
    const response = await api.request(url, options);
    if (response.status === 204) return null;
    const data = await response.json();
    if (!response.ok) {
      if (response.status === 401) login.hidden = false;
      const reason = response.status === 401 ? "Vui lòng đăng nhập để tiếp tục."
        : response.status === 403 ? "Bạn không có quyền thực hiện thao tác này hoặc yêu cầu CSRF không hợp lệ."
          : response.status === 404 ? "Không tìm thấy đề tài trong phạm vi được phép truy cập."
            : response.status === 409 ? "Đề tài có dữ liệu liên quan hoặc vừa thay đổi, không thể thực hiện thao tác."
              : response.status >= 500 ? "Hệ thống chưa xử lý được yêu cầu. Vui lòng thử lại."
                : "Thông tin chưa hợp lệ. Vui lòng kiểm tra và thử lại.";
      const error = new Error(reason);
      error.fields = response.status === 400 ? data : {};
      error.status = response.status;
      throw error;
    }
    return data;
  }

  function textCell(row, value) {
    const cell = row.insertCell();
    cell.textContent = value;
    return cell;
  }

  async function loadList(page = 1) {
    const requestId = ++listRequest;
    const form = document.querySelector("[data-topic-filter]");
    const rows = document.querySelector("[data-topic-rows]");
    const button = form.querySelector('[type="submit"]');
    ui.busy(button, true, "Đang tìm…");
    rows.setAttribute("aria-busy", "true");
    ui.tableState(rows, 5, "Đang tải đề tài…", "", true);
    const query = new URLSearchParams({
      search: form.elements.search.value, status: form.elements.status.value,
      page: String(page), page_size: "12",
    });
    try {
      const data = await fetchData(`/api/topics/?${query}`);
      if (requestId !== listRequest) return;
      currentPage = page;
      rows.replaceChildren();
      for (const topic of data.results) {
        const row = rows.insertRow();
        textCell(row, topic.code);
        const title = document.createElement("a");
        title.href = `/de-tai/${topic.id}/`;
        title.textContent = topic.title;
        row.insertCell().append(title);
        textCell(row, topic.lecturer_name);
        const status = row.insertCell();
        status.dataset.cellStatus = "";
        status.append(ui.badge(topic.status, topic.status_label));
        const actions = row.insertCell();
        const view = document.createElement("a");
        view.href = title.href;
        view.className = "workspace-action";
        view.textContent = "Xem";
        actions.append(view);
        for (const [allowed, label, action] of [
          [capabilities.can_edit, "Sửa", () => openEditor(topic.id)],
          [capabilities.can_delete, "Xóa", () => removeTopic(topic)],
        ]) {
          if (!allowed) continue;
          const button = document.createElement("button");
          button.type = "button";
          button.className = label === "Xóa" ? "workspace-action danger" : "workspace-action";
          button.textContent = label;
          button.setAttribute("aria-label", `${label} đề tài ${topic.code}`);
          button.addEventListener("click", action);
          actions.append(button);
        }
      }
      document.querySelector("[data-result-count]").textContent = `${data.count} đề tài trong phạm vi của bạn.`;
      document.querySelector("[data-page-number]").textContent = `Trang ${page}`;
      document.querySelector("[data-previous-page]").disabled = !data.previous;
      document.querySelector("[data-next-page]").disabled = !data.next;
      if (!data.results.length) ui.tableState(rows, 5, "Không tìm thấy đề tài", "Thử từ khóa khác hoặc chọn tất cả trạng thái.");
    } catch (error) {
      if (requestId !== listRequest) return;
      if (error.status === 404 && page > 1) return loadList(1);
      ui.tableState(rows, 5, "Chưa tải được danh sách", "Đăng nhập hoặc thử tìm kiếm lại.");
      document.querySelector("[data-result-count]").textContent = "";
      tell(error.message || "Không thể tải danh sách.");
    } finally {
      if (requestId === listRequest) {
        ui.busy(button, false);
        rows.removeAttribute("aria-busy");
      }
    }
  }

  async function openEditor(id = null) {
    if (editorLoading) return;
    editorLoading = true;
    const form = document.querySelector("[data-topic-editor]");
    form.reset();
    clearErrors(form);
    try {
      // Selector records are fetched through the Admin-only API, never from a
      // hidden DOM list or a client-supplied role.
      const selector = form.elements.lecturer;
      selector.replaceChildren(new Option("Chọn giảng viên", ""));
      let page = 1;
      let next = true;
      while (next) {
        const result = await fetchData(`/api/topics/lecturers/?page_size=100&page=${page}`);
        for (const lecturer of result.results) selector.add(new Option(lecturer.full_name, String(lecturer.id)));
        next = Boolean(result.next);
        page += 1;
      }
      editingId = id;
      if (id !== null) {
        const topic = await fetchData(`/api/topics/${id}/`);
        for (const name of ["code", "title", "description", "lecturer", "status"]) form.elements[name].value = topic[name];
      } else {
        form.elements.status.value = "DRAFT";
      }
      document.querySelector("#topic-editor-title").textContent = id === null ? "Thêm đề tài nghiên cứu" : "Chỉnh sửa đề tài";
      document.querySelector("[data-topic-dialog]").showModal();
      form.elements.code.focus();
    } catch (error) {
      tell(error.message);
    } finally { editorLoading = false; }
  }

  function clearErrors(form) {
    form.querySelectorAll(".field-error").forEach(element => { element.hidden = true; element.textContent = ""; });
    form.querySelectorAll("[aria-invalid]").forEach(element => element.removeAttribute("aria-invalid"));
    form.querySelector("[data-editor-message]").hidden = true;
  }

  async function saveTopic(event) {
    event.preventDefault();
    const form = event.currentTarget;
    const button = form.querySelector('[type="submit"]');
    clearErrors(form);
    ui.busy(button, true, "Đang lưu…");
    try {
      const data = Object.fromEntries(new FormData(form));
      data.lecturer = Number(data.lecturer);
      await fetchData(editingId === null ? "/api/topics/" : `/api/topics/${editingId}/`, {
        method: editingId === null ? "POST" : "PATCH", data,
      });
      document.querySelector("[data-topic-dialog]").close();
      await loadList(1);
      tell("Đã lưu đề tài.");
    } catch (error) {
      let first = null;
      for (const [name, messages] of Object.entries(error.fields || {})) {
        const field = form.elements.namedItem(name);
        const hint = document.getElementById(`error-${name}`);
        if (!field || !hint) continue;
        hint.textContent = Array.isArray(messages) ? messages.join(" ") : String(messages);
        hint.hidden = false;
        field.setAttribute("aria-invalid", "true");
        first ||= field;
      }
      const hint = form.querySelector("[data-editor-message]");
      hint.textContent = error.message;
      hint.hidden = false;
      first?.focus();
    } finally {
      ui.busy(button, false);
    }
  }

  async function removeTopic(topic) {
    if (!await ui.confirm({ title: "Xóa đề tài nghiên cứu?", description: `${topic.code} · ${topic.title}. Thao tác không thể hoàn tác. Đề tài có đăng ký liên quan sẽ được giữ lại.`, action: "Xóa đề tài", danger: true })) return;
    try {
      await fetchData(`/api/topics/${topic.id}/`, { method: "DELETE" });
      await loadList(1);
      tell("Đã xóa đề tài.");
    } catch (error) { tell(error.message); }
  }

  async function start() {
    try {
      capabilities = await fetchData("/api/topics/capabilities/");
      if (detail) {
        const topic = await fetchData(`/api/topics/${detail.dataset.topicDetail}/`);
        for (const [name, value] of Object.entries({ code: topic.code, title: topic.title, lecturer: topic.lecturer_name, status: topic.status_label, description: topic.description })) {
          document.querySelector(`[data-detail-${name}]`).textContent = value;
        }
        document.querySelector("[data-detail-status]").replaceChildren(ui.badge(topic.status, topic.status_label));
        document.querySelector("[data-topic-content]").hidden = false;
        document.querySelector("[data-detail-manage]").hidden = !capabilities.can_edit;
        const registerButton = document.querySelector("[data-register-topic]");
        if (registerButton) registerButton.hidden = !(capabilities.can_register && topic.status === "OPEN");
        tell("");
        return;
      }
      const scope = capabilities.role === "ADMIN" ? "Quản lý danh mục và phân công giảng viên phụ trách đề tài."
        : capabilities.role === "LECTURER" ? "Chỉ hiển thị đề tài do bạn phụ trách."
          : "Đề tài đã công bố; bạn không có quyền quản trị.";
      document.querySelector("[data-scope]").textContent = scope;
      document.querySelector("[data-create-topic]").hidden = !capabilities.can_create;
      for (const status of capabilities.statuses) {
        document.querySelector("#workspace-status").add(new Option(status.label, status.value));
        document.querySelector("#edit-status").add(new Option(status.label, status.value));
      }
      await loadList(1);
    } catch (error) { tell(error.message || "Không thể kết nối hệ thống."); }
  }

  document.querySelector("[data-topic-filter]")?.addEventListener("submit", event => { event.preventDefault(); loadList(1); });
  document.querySelector("[data-create-topic]")?.addEventListener("click", () => openEditor());
  document.querySelector("[data-close-editor]")?.addEventListener("click", () => document.querySelector("[data-topic-dialog]").close());
  document.querySelector("[data-cancel-topic]")?.addEventListener("click", () => document.querySelector("[data-topic-dialog]").close());
  document.querySelector("[data-topic-editor]")?.addEventListener("submit", saveTopic);
  document.querySelector("[data-previous-page]")?.addEventListener("click", () => loadList(currentPage - 1));
  document.querySelector("[data-next-page]")?.addEventListener("click", () => loadList(currentPage + 1));
  start();
})();
