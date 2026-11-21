"use strict";

(() => {
  const workspace = document.querySelector("[data-registration-workspace]");
  const detailButton = document.querySelector("[data-register-topic]");
  if (!workspace && !detailButton) return;
  const api = window.KHCNAuth;
  const ui = window.KHCNUI;
  const message = document.querySelector("[data-registration-message]");
  const login = document.querySelector("[data-registration-login]");
  let capabilities = null;
  let recordPage = 1;
  let candidatePage = 1;
  let recordRequest = 0;
  let candidateRequest = 0;
  const knownTopics = new Set();

  function tell(text) {
    message.textContent = text;
    message.hidden = !text;
  }

  async function fetchData(url, options) {
    const response = await api.request(url, options);
    const data = await response.json();
    if (!response.ok) {
      if (response.status === 401) login.hidden = false;
      const text = response.status === 401 ? "Vui lòng đăng nhập để tiếp tục."
        : response.status === 403 ? "Bạn không có quyền thực hiện yêu cầu hoặc kiểm tra CSRF không hợp lệ."
          : response.status === 404 ? "Không tìm thấy dữ liệu trong phạm vi được phép truy cập."
            : response.status >= 500 ? "Hệ thống chưa xử lý được yêu cầu. Vui lòng thử lại."
              : data.detail || "Thông tin yêu cầu chưa hợp lệ. Vui lòng kiểm tra và thử lại.";
      const error = new Error(text);
      error.status = response.status;
      error.code = data.code;
      throw error;
    }
    return data;
  }

  function cell(row, text) {
    const element = row.insertCell();
    element.textContent = text;
    return element;
  }

  function subtext(element, text) {
    const small = document.createElement("small");
    small.textContent = text;
    element.append(small);
  }

  async function loadRecords(page = 1) {
    const requestId = ++recordRequest;
    const form = document.querySelector("[data-registration-filter]");
    const query = new URLSearchParams({ page: String(page), page_size: "12" });
    for (const name of ["status", "topic", "student"]) {
      if (form.elements[name].value) query.set(name, form.elements[name].value);
    }
    const button = form.querySelector('[type="submit"]');
    const rows = document.querySelector("[data-registration-rows]");
    ui.busy(button, true, "Đang lọc…");
    rows.setAttribute("aria-busy", "true");
    ui.tableState(rows, 6, "Đang tải đăng ký…", "", true);
    try {
      const data = await fetchData(`/api/registrations/?${query}`);
      if (requestId !== recordRequest) return;
      recordPage = page;
      rows.replaceChildren();
      for (const registration of data.results) {
        if (capabilities.role === "STUDENT") knownTopics.add(registration.topic);
        const row = rows.insertRow();
        row.dataset.registrationId = String(registration.id);
        cell(row, `#${registration.id}`);
        const topicCell = row.insertCell();
        const link = document.createElement("a");
        link.href = `/de-tai/${registration.topic}/`;
        link.textContent = `${registration.topic_code}: ${registration.topic_title}`;
        topicCell.append(link);
        subtext(topicCell, `ID đề tài: ${registration.topic} · ${registration.lecturer_name}`);
        const student = cell(row, registration.student_name);
        subtext(student, `ID sinh viên: ${registration.student}`);
        subtext(student, registration.student_email);
        row.insertCell().append(ui.badge(registration.status, registration.status_label));
        const audit = cell(row, registration.reviewer_name || (registration.status === "PENDING" ? "Chưa xét duyệt" : "Chưa có thông tin xét duyệt"));
        if (registration.reviewed_at) subtext(audit, new Date(registration.reviewed_at).toLocaleString("vi-VN"));
        const actions = row.insertCell();
        if (capabilities.can_review && registration.status === "PENDING") {
          for (const [label, action] of [["Chấp nhận", "approve"], ["Từ chối", "reject"]]) {
            const button = document.createElement("button");
            button.type = "button";
            button.className = action === "reject" ? "workspace-action danger" : "workspace-action";
            button.textContent = label;
            button.setAttribute("aria-label", `${label} đăng ký #${registration.id} của ${registration.student_name}`);
            button.addEventListener("click", () => decide(registration, action, button));
            actions.append(button);
          }
        } else {
          actions.textContent = registration.status === "PENDING" ? "Chờ xét duyệt" : "Đã xử lý";
        }
      }
      document.querySelector("[data-registration-count]").textContent = `${data.count} đăng ký trong phạm vi của bạn.`;
      document.querySelector("[data-registration-page]").textContent = `Trang ${page}`;
      document.querySelector("[data-registration-prev]").disabled = !data.previous;
      document.querySelector("[data-registration-next]").disabled = !data.next;
      if (!data.results.length) ui.tableState(rows, 6, "Chưa có đăng ký phù hợp", capabilities.role === "STUDENT" ? "Chọn đề tài đang mở ở bên dưới để gửi đăng ký, hoặc thay đổi bộ lọc." : "Các yêu cầu trong phạm vi phụ trách sẽ xuất hiện tại đây. Thử thay đổi bộ lọc.");
    } catch (error) {
      if (requestId !== recordRequest) return;
      if (error.status === 404 && page > 1) return loadRecords(1);
      ui.tableState(rows, 6, "Chưa tải được đăng ký", "Vui lòng thử lọc lại hoặc tải lại trang.");
      document.querySelector("[data-registration-count]").textContent = "";
      tell(error.message || "Không thể tải đăng ký.");
    } finally {
      if (requestId === recordRequest) {
        ui.busy(button, false);
        rows.removeAttribute("aria-busy");
      }
    }
  }

  async function loadCandidates(page = 1) {
    const requestId = ++candidateRequest;
    const form = document.querySelector("[data-candidate-search]");
    const query = new URLSearchParams({ status: "OPEN", search: form.elements.search.value, page: String(page), page_size: "12" });
    const rows = document.querySelector("[data-candidate-rows]");
    const button = form.querySelector('[type="submit"]');
    ui.busy(button, true, "Đang tìm…");
    rows.setAttribute("aria-busy", "true");
    ui.tableState(rows, 4, "Đang tải đề tài mở…", "", true);
    try {
      const data = await fetchData(`/api/topics/?${query}`);
      if (requestId !== candidateRequest) return;
      candidatePage = page;
      rows.replaceChildren();
      for (const topic of data.results) {
        const row = rows.insertRow();
        cell(row, topic.code);
        const link = document.createElement("a");
        link.href = `/de-tai/${topic.id}/`;
        link.textContent = topic.title;
        row.insertCell().append(link);
        cell(row, topic.lecturer_name);
        const button = document.createElement("button");
        button.type = "button";
        button.className = "btn btn-primary";
        button.dataset.registerCandidate = String(topic.id);
        button.disabled = knownTopics.has(topic.id);
        button.textContent = button.disabled ? "Đã đăng ký" : "Đăng ký";
        button.addEventListener("click", () => submitTopic(topic.id, button));
        row.insertCell().append(button);
      }
      document.querySelector("[data-candidate-count]").textContent = `${data.count} đề tài đang mở.`;
      document.querySelector("[data-candidate-page]").textContent = `Trang ${page}`;
      document.querySelector("[data-candidate-prev]").disabled = !data.previous;
      document.querySelector("[data-candidate-next]").disabled = !data.next;
      if (!data.results.length) ui.tableState(rows, 4, "Chưa tìm thấy đề tài đang mở", "Thử từ khóa khác hoặc quay lại sau khi có đề tài mới.");
    } catch (error) {
      if (requestId === candidateRequest) {
        ui.tableState(rows, 4, "Chưa tải được đề tài", "Thử tìm kiếm lại để tiếp tục.");
        tell(error.message);
      }
    } finally {
      if (requestId === candidateRequest) {
        ui.busy(button, false);
        rows.removeAttribute("aria-busy");
      }
    }
  }

  async function submitTopic(topicId, button) {
    button.disabled = true;
    button.textContent = "Đang gửi...";
    try {
      await fetchData("/api/registrations/", { method: "POST", data: { topic: topicId } });
      knownTopics.add(topicId);
      button.textContent = "Đã đăng ký";
      if (workspace) await loadRecords(1);
      tell("Đã gửi yêu cầu đăng ký. Vui lòng theo dõi kết quả xét duyệt.");
    } catch (error) {
      const duplicate = error.code === "duplicate_registration";
      button.disabled = duplicate;
      button.textContent = duplicate ? "Đã đăng ký" : "Đăng ký";
      tell(error.message || "Không thể gửi đăng ký.");
    }
  }

  async function decide(registration, action, button) {
    const label = action === "approve" ? "Chấp nhận" : "Từ chối";
    if (!await ui.confirm({ title: `${label} đăng ký?`, description: `Đăng ký #${registration.id} · ${registration.student_name} · ${registration.topic_code}. Quyết định sẽ được lưu và không thể đổi lại.`, action: `${label} đăng ký`, danger: action === "reject" })) return;
    ui.busy(button, true, "Đang lưu…");
    try {
      await fetchData(`/api/registrations/${registration.id}/${action}/`, { method: "POST", data: {} });
      await loadRecords(recordPage);
      tell(action === "approve" ? "Đã chấp nhận đăng ký." : "Đã từ chối đăng ký.");
    } catch (error) {
      await loadRecords(recordPage);
      tell(error.message || "Không thể xét duyệt.");
      ui.busy(button, false);
    }
  }

  async function start() {
    try {
      capabilities = await fetchData("/api/registrations/capabilities/");
      const role = capabilities.role;
      document.querySelector("[data-registration-title]").textContent = role === "STUDENT" ? "Đăng ký của tôi" : role === "LECTURER" ? "Xét duyệt đăng ký" : "Quản lý đăng ký đề tài";
      document.querySelector("[data-registration-scope]").textContent = role === "STUDENT" ? "Theo dõi trạng thái và kết quả đăng ký tham gia nghiên cứu của bạn." : role === "LECTURER" ? "Xét duyệt đăng ký thuộc các đề tài bạn phụ trách." : "Theo dõi và xét duyệt đăng ký tham gia nghiên cứu toàn hệ thống.";
      document.querySelector("[data-student-filter]").hidden = role !== "ADMIN";
      for (const value of capabilities.statuses) document.querySelector("#registration-status").add(new Option(value.label, value.value));
      document.querySelector("[data-registration-content]").hidden = false;
      await loadRecords(1);
      if (capabilities.can_register) {
        document.querySelector("[data-registration-candidates]").hidden = false;
        await loadCandidates(1);
      }
    } catch (error) {
      document.querySelector("[data-registration-scope]").textContent = "Chưa có quyền truy cập dữ liệu đăng ký.";
      tell(error.message || "Không thể kết nối hệ thống.");
    }
  }

  detailButton?.addEventListener("click", () => submitTopic(Number(detailButton.dataset.registerTopic), detailButton));
  if (!workspace) return;
  document.querySelector("[data-registration-filter]").addEventListener("submit", event => { event.preventDefault(); loadRecords(1); });
  document.querySelector("[data-candidate-search]").addEventListener("submit", event => { event.preventDefault(); loadCandidates(1); });
  document.querySelector("[data-registration-prev]").addEventListener("click", () => loadRecords(recordPage - 1));
  document.querySelector("[data-registration-next]").addEventListener("click", () => loadRecords(recordPage + 1));
  document.querySelector("[data-candidate-prev]").addEventListener("click", () => loadCandidates(candidatePage - 1));
  document.querySelector("[data-candidate-next]").addEventListener("click", () => loadCandidates(candidatePage + 1));
  start();
})();
