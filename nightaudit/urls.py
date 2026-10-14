from django.urls import path

from .views import (
    CityLedgerView,
    FlashReportView,
    GuestLedgerView,
    NightAuditView,
    OccupancyReportView,
    PaymentsReportView,
    RevenueReportView,
)

urlpatterns = [
    path('night-audit/', NightAuditView.as_view(), name='night-audit'),
    path('reports/flash/', FlashReportView.as_view(), name='report-flash'),
    path('reports/occupancy/', OccupancyReportView.as_view(), name='report-occupancy'),
    path('reports/revenue/', RevenueReportView.as_view(), name='report-revenue'),
    path('reports/payments/', PaymentsReportView.as_view(), name='report-payments'),
    path('reports/guest-ledger/', GuestLedgerView.as_view(), name='report-guest-ledger'),
    path('reports/city-ledger/', CityLedgerView.as_view(), name='report-city-ledger'),
]
