from django.urls import path
from rest_framework.routers import SimpleRouter

from .views import ExpenseApprovalPolicyViewSet, ExpenseViewSet, ReceiptUploadView

router = SimpleRouter()
router.register("expenses", ExpenseViewSet, basename="expense")
router.register(
    "expense-approval-policies",
    ExpenseApprovalPolicyViewSet,
    basename="expense-approval-policy",
)

urlpatterns = [
    path("receipts/", ReceiptUploadView.as_view(), name="receipt-upload"),
] + router.urls
