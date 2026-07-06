from rest_framework.routers import SimpleRouter

from .views import InvoiceViewSet

router = SimpleRouter()
router.register("invoices", InvoiceViewSet, basename="invoice")

urlpatterns = router.urls
