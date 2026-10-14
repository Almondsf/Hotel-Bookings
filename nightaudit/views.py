import csv
from datetime import timedelta

from django.http import HttpResponse
from rest_framework import serializers
from rest_framework.response import Response
from rest_framework.views import APIView

from authentication.permissions import HasCapability
from booking.staff_views import parse_date_param
from hotel.clock import business_date

from . import reports, services
from .models import BusinessDay

MAX_REPORT_DAYS = 366


def date_range(request, default_days=0):
    """?from=&to= (inclusive), defaulting to the current business date."""
    end = parse_date_param(request.query_params, 'to') or business_date()
    start = parse_date_param(request.query_params, 'from') or end - timedelta(days=default_days)
    if start > end:
        raise serializers.ValidationError({'from': "Start date must not be after the end date."})
    if (end - start).days >= MAX_REPORT_DAYS:
        raise serializers.ValidationError({'from': f"Reports cover at most {MAX_REPORT_DAYS} days."})
    return start, end


def csv_response(filename, rows, columns):
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    writer = csv.writer(response)
    writer.writerow(columns)
    for row in rows:
        # Neutralise spreadsheet formula injection from user-entered text
        writer.writerow([_safe_cell(row.get(c)) for c in columns])
    return response


def _safe_cell(value):
    text = '' if value is None else str(value)
    return "'" + text if text[:1] in ('=', '+', '-', '@') and not _is_number(text) else text


def _is_number(text):
    try:
        float(text)
        return True
    except ValueError:
        return False


class ReportView(APIView):
    permission_classes = [HasCapability('reports.view')]

    def respond(self, request, data, rows_key=None, columns=None, filename='report.csv'):
        if request.query_params.get('export') == 'csv' and rows_key:
            return csv_response(filename, data[rows_key] if rows_key != '.' else data, columns)
        return Response(data)


class FlashReportView(ReportView):
    """Manager's flash for ?date= (closed days come from the night-audit snapshot)."""

    def get(self, request):
        day = parse_date_param(request.query_params, 'date') or business_date()
        closed = BusinessDay.objects.filter(date=day, status=BusinessDay.Status.CLOSED).first()
        if closed and closed.statistics:
            return Response({**closed.statistics, 'source': 'night_audit'})
        return Response({**reports.flash(day), 'source': 'live'})


class OccupancyReportView(ReportView):
    columns = ['date', 'actual', 'rooms_available', 'rooms_sold', 'occupancy_percent', 'room_revenue', 'adr', 'revpar']

    def get(self, request):
        start, end = date_range(request, default_days=6)
        rows = reports.occupancy(start, end)
        return self.respond(request, rows, '.', self.columns, f'occupancy_{start}_{end}.csv')


class RevenueReportView(ReportView):
    def get(self, request):
        start, end = date_range(request)
        return self.respond(request, reports.revenue(start, end), 'categories',
                            ['category', 'name', 'net', 'tax', 'gross'], f'revenue_{start}_{end}.csv')


class PaymentsReportView(ReportView):
    def get(self, request):
        start, end = date_range(request)
        return self.respond(request, reports.payments(start, end), 'by_method',
                            ['method', 'received', 'refunded', 'net'], f'payments_{start}_{end}.csv')


class GuestLedgerView(ReportView):
    def get(self, request):
        return self.respond(request, reports.guest_ledger(), 'folios',
                            ['folio', 'name', 'room', 'booking_status', 'charges', 'payments', 'balance'], 'guest_ledger.csv')


class CityLedgerView(ReportView):
    def get(self, request):
        return self.respond(request, reports.city_ledger(), 'accounts',
                            ['code', 'name', 'credit_limit', 'current', '31_60', '61_90', 'over_90', 'balance'],
                            'city_ledger.csv')


class NightAuditView(APIView):
    """GET: the open business day and what blocks closing it. POST {auto_no_show}: run the audit."""
    permission_classes = [HasCapability('night_audit.run')]

    def get(self, request):
        day = services.current_day()
        history = BusinessDay.objects.filter(status=BusinessDay.Status.CLOSED)[:14]
        return Response({
            'business_date': day.date,
            'exceptions': services.exceptions(day.date),
            'history': [{'date': d.date, 'closed_at': d.closed_at, 'statistics': d.statistics} for d in history],
        })

    def post(self, request):
        _, summary = services.run(request=request, auto_no_show=bool(request.data.get('auto_no_show')))
        return Response(summary)
