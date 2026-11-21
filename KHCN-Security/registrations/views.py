from django.shortcuts import render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET


@require_GET
@never_cache
def registration_workspace(request):
    return render(request, "registrations/workspace.html")
