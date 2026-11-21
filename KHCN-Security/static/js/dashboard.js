"use strict";

(() => {
  if (!document.querySelector("[data-dashboard]")) return;
  const api = window.KHCNAuth;
  const ui = window.KHCNUI;
  const message = document.querySelector("[data-dashboard-message]");

  async function get(url) {
    const response = await api.request(url);
    if (!response.ok) throw new Error("Không thể tải một phần dữ liệu. Hãy tải lại trang để thử lại.");
    return response.json();
  }

  function showTopics(data) {
    document.querySelector('[data-stat="topics"]').textContent = data.count.toLocaleString("vi-VN");
    const rows = document.querySelector("[data-dashboard-topics]");
    rows.replaceChildren();
    if (!data.results.length) return ui.tableState(rows, 3, "Chưa có đề tài", "Đề tài trong phạm vi của bạn sẽ xuất hiện tại đây.");
    for (const topic of data.results) {
      const row = rows.insertRow();
      row.insertCell().textContent = topic.code;
      const link = document.createElement("a");
      link.href = `/de-tai/${topic.id}/`;
      link.textContent = topic.title;
      const cell = row.insertCell();
      cell.append(link);
      const small = document.createElement("small");
      small.textContent = topic.lecturer_name;
      cell.append(small);
      row.insertCell().append(ui.badge(topic.status, topic.status_label));
    }
  }

  function showRegistrations(data) {
    const list = document.querySelector("[data-dashboard-registrations]");
    list.replaceChildren();
    if (!data.results.length) {
      const empty = document.createElement("div");
      empty.className = "empty-state";
      const heading = document.createElement("h3");
      heading.textContent = "Chưa có đăng ký";
      const text = document.createElement("p");
      text.textContent = "Các đăng ký mới sẽ xuất hiện tại đây.";
      empty.append(heading, text);
      list.append(empty);
      return;
    }
    for (const record of data.results) {
      const item = document.createElement("article");
      item.className = "activity-item";
      const title = document.createElement("a");
      title.href = "/dang-ky/";
      title.textContent = `${record.topic_code} · ${record.topic_title}`;
      const meta = document.createElement("div");
      meta.className = "activity-meta";
      meta.textContent = `${record.student_name} · ${new Date(record.created_at).toLocaleDateString("vi-VN")}`;
      item.append(title, ui.badge(record.status, record.status_label), meta);
      list.append(item);
    }
  }

  async function start() {
    const user = await api.ready;
    if (!user) {
      document.querySelector("[data-dashboard-login]").hidden = false;
      document.querySelector("[data-dashboard-scope]").textContent = "Đăng nhập để truy cập số liệu dành cho tài khoản của bạn.";
      return;
    }
    const role = user.roles.includes("ADMIN") ? "ADMIN" : user.roles.includes("LECTURER") ? "LECTURER" : user.roles.includes("STUDENT") ? "STUDENT" : null;
    if (!role) {
      document.querySelector("[data-dashboard-scope]").textContent = "Tài khoản chưa được phân vai trò.";
      message.textContent = "Liên hệ quản trị viên để được cấp quyền sử dụng.";
      message.hidden = false;
      return;
    }
    const scopes = { ADMIN: "Tổng hợp đề tài và đăng ký toàn hệ thống.", LECTURER: "Theo dõi đề tài và đăng ký thuộc phạm vi bạn phụ trách.", STUDENT: "Tra cứu đề tài đã công bố và theo dõi đăng ký của chính bạn." };
    document.querySelector("[data-dashboard-scope]").textContent = scopes[role];
    document.querySelector("[data-dashboard-role]").textContent = ui.roles[role];
    document.querySelector("[data-dashboard-welcome]").textContent = role === "STUDENT" ? "Bắt đầu từ một đề tài bạn quan tâm" : "Theo dõi công việc nghiên cứu của bạn";
    document.querySelector("[data-dashboard-description]").textContent = role === "STUDENT" ? "Chọn đề tài đang mở, gửi đăng ký và theo dõi phản hồi từ giảng viên." : "Xem danh mục đề tài và xử lý các yêu cầu đăng ký đang chờ xét duyệt.";
    const action = document.querySelector("[data-dashboard-action]");
    action.firstChild.textContent = role === "STUDENT" ? "Đăng ký đề tài " : "Xét duyệt đăng ký ";
    if (role === "STUDENT") document.querySelector("[data-registration-stat-caption]").textContent = "Đăng ký của chính bạn";
    if (role === "LECTURER") document.querySelector("[data-topic-stat-caption]").textContent = "Đề tài bạn phụ trách";
    document.querySelector("[data-dashboard-content]").hidden = false;
    ui.tableState(document.querySelector("[data-dashboard-topics]"), 3, "Đang tải đề tài…", "", true);
    const registrationList = document.querySelector("[data-dashboard-registrations]");
    registrationList.textContent = "Đang tải đăng ký…";
    const jobs = [
      get("/api/topics/?page_size=5").then(showTopics).catch(error => { ui.tableState(document.querySelector("[data-dashboard-topics]"), 3, "Chưa tải được đề tài", "Tải lại trang để thử lại."); throw error; }),
      get("/api/topics/?status=OPEN&page_size=1").then(data => { document.querySelector('[data-stat="open"]').textContent = data.count.toLocaleString("vi-VN"); }),
      get("/api/registrations/?status=PENDING&page_size=1").then(data => { document.querySelector('[data-stat="pending"]').textContent = data.count.toLocaleString("vi-VN"); }),
      get("/api/registrations/?status=APPROVED&page_size=1").then(data => { document.querySelector('[data-stat="approved"]').textContent = data.count.toLocaleString("vi-VN"); }),
      get("/api/registrations/?page_size=4").then(showRegistrations).catch(error => { registrationList.textContent = "Chưa tải được đăng ký. Hãy tải lại trang để thử lại."; throw error; }),
    ];
    const results = await Promise.allSettled(jobs);
    if (results.some(result => result.status === "rejected")) {
      message.textContent = "Một phần dữ liệu chưa tải được hoặc bạn chưa được cấp quyền xem. Giá trị chưa tải được hiển thị dấu —. Hãy tải lại trang để thử lại.";
      message.hidden = false;
    }
  }
  start();
})();
