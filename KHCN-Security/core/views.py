from django.core.paginator import Paginator
from django.db import DatabaseError, connection
from django.db.models import Count, Q
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from topics.models import Topic


@require_GET
@never_cache
def dashboard(request):
    return render(request, "core/dashboard.html")


@require_GET
def home(request):
    public = Topic.objects.exclude(status=Topic.Status.DRAFT)
    summary = public.aggregate(
        total=Count("pk"), opened=Count("pk", filter=Q(status=Topic.Status.OPEN))
    )
    query = request.GET.get("q", "").strip()[:150]
    status = request.GET.get("status", "")
    topics = public.select_related("lecturer")
    if query:
        topics = topics.filter(
            Q(code__icontains=query)
            | Q(title__icontains=query)
            | Q(lecturer__full_name__icontains=query)
        )
    valid_statuses = [
        (value, label)
        for value, label in Topic.Status.choices
        if value != Topic.Status.DRAFT
    ]
    if status in dict(valid_statuses):
        topics = topics.filter(status=status)
    else:
        status = ""
    page = Paginator(topics, 12).get_page(request.GET.get("page"))
    return render(
        request,
        "core/home.html",
        {
            "page_obj": page,
            "summary": summary,
            "query": query,
            "selected_status": status,
            "statuses": valid_statuses,
        },
    )


@require_GET
def health(request):
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except DatabaseError:
        response = JsonResponse(
            {"status": "unavailable", "database": "unavailable"}, status=503
        )
    else:
        response = JsonResponse({"status": "ok", "database": "ok"})
    response["Cache-Control"] = "no-store"
    return response
