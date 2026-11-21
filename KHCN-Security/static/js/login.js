"use strict";

const loginForm = document.querySelector("#login-form");
document.querySelector("[data-password-toggle]")?.addEventListener("click", event => {
  const button = event.currentTarget;
  const field = loginForm.elements.password;
  const visible = field.type === "password";
  field.type = visible ? "text" : "password";
  button.textContent = visible ? "Ẩn" : "Hiện";
  button.setAttribute("aria-pressed", String(visible));
  button.setAttribute("aria-label", visible ? "Ẩn mật khẩu" : "Hiện mật khẩu");
});
loginForm?.addEventListener("submit", async event => {
  event.preventDefault();
  const button = loginForm.querySelector('button[type="submit"]');
  const status = loginForm.querySelector("[data-login-status]");
  for (const name of ["email", "password"]) {
    loginForm.elements[name].removeAttribute("aria-invalid");
    document.querySelector(`#${name}-error`).hidden = true;
  }
  status.textContent = "Đang đăng nhập...";
  window.KHCNUI.busy(button, true, "Đang đăng nhập…");
  try {
    const response = await window.KHCNAuth.send("/api/auth/login/", {
      method: "POST",
      data: {
        email: loginForm.elements.email.value,
        password: loginForm.elements.password.value,
      },
    });
    if (response.ok) {
      loginForm.elements.password.value = "";
      window.location.assign("/tong-quan/");
      return;
    }
    const payload = await response.json();
    let firstError = null;
    for (const name of ["email", "password"]) {
      if (Array.isArray(payload[name])) {
        const error = document.querySelector(`#${name}-error`);
        error.textContent = payload[name].join(" ");
        error.hidden = false;
        loginForm.elements[name].setAttribute("aria-invalid", "true");
        firstError ||= loginForm.elements[name];
      }
    }
    if (firstError) firstError.focus();
    status.textContent = response.status === 429
      ? "Bạn đã thử nhiều lần. Vui lòng chờ một phút rồi thử lại."
      : response.status === 401
        ? "Email hoặc mật khẩu không đúng."
        : response.status === 403
          ? "Yêu cầu không hợp lệ. Hãy tải lại trang và thử lại."
          : "Không thể đăng nhập. Vui lòng kiểm tra thông tin và thử lại.";
    loginForm.elements.password.value = "";
  } catch {
    status.textContent = "Không thể kết nối. Vui lòng thử lại sau.";
  } finally {
    window.KHCNUI.busy(button, false);
  }
});
