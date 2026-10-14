from rest_framework.routers import SimpleRouter

from .views import TicketViewSet

router = SimpleRouter()
router.register('tickets', TicketViewSet, basename='maintenance-ticket')

urlpatterns = router.urls
