from rest_framework.routers import SimpleRouter

from .views import CorporateAccountViewSet, ExchangeRateViewSet, FolioViewSet, InvoiceViewSet, TaxRuleViewSet

router = SimpleRouter()
router.register('folios', FolioViewSet, basename='folio')
router.register('invoices', InvoiceViewSet, basename='invoice')
router.register('accounts', CorporateAccountViewSet, basename='account')
router.register('tax-rules', TaxRuleViewSet, basename='tax-rule')
router.register('exchange-rates', ExchangeRateViewSet, basename='exchange-rate')

urlpatterns = router.urls
