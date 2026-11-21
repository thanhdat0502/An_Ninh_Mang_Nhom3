"""Cookie and CSRF policy shared by authentication and the public auth endpoints."""

from urllib.parse import urlsplit

from django.conf import settings
from rest_framework.authentication import CSRFCheck
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import SAFE_METHODS, BasePermission


def enforce_transport(request):
    if request.is_secure():
        return
    hostname = urlsplit(f"//{request.get_host()}").hostname
    if not settings.DEBUG or hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise PermissionDenied("Chỉ cho phép HTTP trên localhost khi DEBUG=True.")


def enforce_csrf(request):
    if request.method in SAFE_METHODS:
        return
    check = CSRFCheck(lambda request: None)
    check.process_request(request)
    if check.process_view(request, None, (), {}):
        # Never echo header/cookie/body values or implementation details.
        raise PermissionDenied("Kiểm tra CSRF thất bại. Vui lòng tải lại trang.")


class RequireCSRF(BasePermission):
    def has_permission(self, request, view):
        enforce_csrf(request)
        return True


def set_auth_cookies(response, request, refresh):
    access = refresh.access_token
    policy = {
        "httponly": True,
        "secure": request.is_secure() or not settings.DEBUG,
        "samesite": settings.JWT_COOKIE_SAMESITE,
    }
    for name, token, path in (
        (settings.JWT_ACCESS_COOKIE, access, settings.JWT_ACCESS_COOKIE_PATH),
        (settings.JWT_REFRESH_COOKIE, refresh, settings.JWT_REFRESH_COOKIE_PATH),
    ):
        response.set_cookie(
            name,
            str(token),
            max_age=max(0, token["exp"] - token["iat"]),
            path=path,
            **policy,
        )
    return response


def clear_auth_cookies(response, request):
    for name, path in (
        (settings.JWT_ACCESS_COOKIE, settings.JWT_ACCESS_COOKIE_PATH),
        (settings.JWT_REFRESH_COOKIE, settings.JWT_REFRESH_COOKIE_PATH),
    ):
        response.set_cookie(
            name,
            "",
            max_age=0,
            path=path,
            httponly=True,
            secure=request.is_secure() or not settings.DEBUG,
            samesite=settings.JWT_COOKIE_SAMESITE,
        )
    return response
