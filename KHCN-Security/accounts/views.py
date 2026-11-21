from django.shortcuts import render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET


@require_GET
@never_cache
def login_page(request):
    return render(request, "accounts/login.html")


@require_GET
@never_cache
def workspace(request):
    # Private data is fetched only through the JWT-protected API.
    return render(request, "accounts/workspace.html")
