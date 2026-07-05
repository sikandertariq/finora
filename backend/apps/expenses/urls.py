from django.urls import path
from rest_framework.routers import SimpleRouter

from .views import ExpenseViewSet, ReceiptUploadView

router = SimpleRouter()
router.register("expenses", ExpenseViewSet, basename="expense")

urlpatterns = [
    path("receipts/", ReceiptUploadView.as_view(), name="receipt-upload"),
] + router.urls
