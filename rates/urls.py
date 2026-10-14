from rest_framework.routers import SimpleRouter

from .views import RatePlanPriceViewSet, RatePlanViewSet, RateRestrictionViewSet

router = SimpleRouter()
router.register('plans', RatePlanViewSet, basename='rate-plan')
router.register('prices', RatePlanPriceViewSet, basename='rate-price')
router.register('restrictions', RateRestrictionViewSet, basename='rate-restriction')

urlpatterns = router.urls
