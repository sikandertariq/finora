from django.db import connection
from django.http import JsonResponse


def health(request):
    """Small unauthenticated readiness probe for the reverse proxy and deploys."""
    connection.ensure_connection()
    return JsonResponse({"status": "ok"})
