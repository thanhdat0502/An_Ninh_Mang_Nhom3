from django.shortcuts import render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET


@require_GET
@never_cache
def topic_workspace(request):
    # Templates contain no protected records; all data comes from JWT API calls.
    return render(request, "topics/workspace.html")


@require_GET
@never_cache
def topic_detail(request, pk):
    return render(request, "topics/detail.html", {"topic_id": pk})
