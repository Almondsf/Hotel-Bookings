from django.urls import path

from .views import GuestAnonymiseView, GuestExportView

urlpatterns = [
    path('guests/<int:guest_id>/export/', GuestExportView.as_view(), name='guest-export'),
    path('guests/<int:guest_id>/anonymise/', GuestAnonymiseView.as_view(), name='guest-anonymise'),
]
