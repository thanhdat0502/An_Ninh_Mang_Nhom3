"use strict";

// JWT values remain entirely in HttpOnly cookies. Only a masked CSRF token
// crosses into JavaScript, and only within the lifetime of a request.
window.KHCNAuth = (() => {
  let refreshPromise = null;

  async function csrfToken() {
    const response = await fetch("/api/auth/csrf/", {
      credentials: "same-origin", cache: "no-store",
    });
    if (!response.ok) throw new Error("Không thể xác minh yêu cầu. Hãy tải lại trang.");
    return (await response.json()).csrfToken;
  }

  async function send(url, { method = "GET", data } = {}) {
    // Limit this helper to the same-origin API. Never forward CSRF to a URL
    // supplied by a caller on another origin.
    const target = new URL(url, window.location.origin);
    if (target.origin !== window.location.origin || !target.pathname.startsWith("/api/")) {
      throw new Error("Địa chỉ yêu cầu không hợp lệ.");
    }
    const headers = { Accept: "application/json" };
    if (!["GET", "HEAD", "OPTIONS"].includes(method)) {
      headers["X-CSRFToken"] = await csrfToken();
    }
    if (data !== undefined) headers["Content-Type"] = "application/json";
    return fetch(target, {
      method, credentials: "same-origin", cache: "no-store", headers,
      body: data === undefined ? undefined : JSON.stringify(data),
    });
  }

  async function refresh() {
    if (!refreshPromise) {
      refreshPromise = send("/api/auth/refresh/", { method: "POST" })
        .then(response => response.ok)
        .finally(() => { refreshPromise = null; });
    }
    return refreshPromise;
  }

  async function request(url, options) {
    const response = await send(url, options);
    if (response.status === 401 && await refresh()) return send(url, options);
    return response;
  }

  function showUser(user) {
    const label = document.querySelector("[data-current-user]");
    const login = document.querySelector("[data-login-link]");
    const logout = document.querySelector("[data-logout]");
    if (label) {
      label.textContent = user ? user.full_name : "";
      label.hidden = !user;
    }
    if (login) login.hidden = Boolean(user);
    if (logout) logout.hidden = !user;
    const roles = { ADMIN: "Quản trị viên", LECTURER: "Giảng viên", STUDENT: "Sinh viên" };
    const role = user?.roles.find(value => value === "ADMIN")
      || user?.roles.find(value => value === "LECTURER")
      || user?.roles.find(value => value === "STUDENT");
    const roleLabel = document.querySelector("[data-current-role]");
    if (roleLabel) roleLabel.textContent = roles[role] || (user ? "Chưa có vai trò" : "Khách truy cập");
    const initial = document.querySelector("[data-user-initial]");
    if (initial) initial.textContent = user?.full_name?.trim().split(/\s+/).pop()?.charAt(0).toUpperCase() || "K";
    const registrationNav = document.querySelector("[data-registration-nav]");
    if (registrationNav) registrationNav.textContent = role === "STUDENT" ? "Đăng ký của tôi" : role ? "Xét duyệt đăng ký" : "Đăng ký & xét duyệt";
    // Visibility is only a UX hint; this API checks Groups and model permissions.
    if (role === "ADMIN") {
      request("/api/accounts/capabilities/").then(response => {
        const link = document.querySelector("[data-admin-nav]");
        if (link) link.hidden = !response.ok;
      }).catch(() => {});
    }
  }

  async function loadUser() {
    try {
      const response = await request("/api/auth/me/");
      const user = response.ok ? await response.json() : null;
      showUser(user);
      return user;
    } catch {
      showUser(null);
      return null;
    }
  }

  document.querySelector("[data-logout]")?.addEventListener("click", async event => {
    const button = event.currentTarget;
    button.disabled = true;
    try {
      const response = await send("/api/auth/logout/", { method: "POST" });
      if (!response.ok) throw new Error("Không thể đăng xuất. Vui lòng thử lại.");
      showUser(null);
      window.location.assign("/dang-nhap/");
    } catch {
      const notice = document.querySelector("[data-auth-notice]");
      if (notice) {
        notice.textContent = "Không thể đăng xuất. Vui lòng thử lại.";
        notice.hidden = false;
      }
      button.disabled = false;
    }
  });

  // Avoid racing an automatic refresh with a user submitting the login form.
  const ready = document.querySelector("#login-form") ? Promise.resolve(null) : loadUser();
  return { send, request, ready };
})();
