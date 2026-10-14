"""
Channex API client (https://docs.channex.io).

Only the calls the PMS needs: publish availability, rates & restrictions;
read and acknowledge booking revisions. Before go-live the integration must
be certified against Channex's staging environment (CHANNEX_BASE_URL).
"""
import requests
from django.conf import settings

from hotel.errors import DomainError


class ChannelError(DomainError):
    status_code = 502


class ChannexClient:
    timeout = 30

    def __init__(self, connection):
        self.connection = connection
        self.base = settings.CHANNEX_BASE_URL.rstrip('/')

    def _request(self, method, path, **kwargs):
        try:
            response = requests.request(method, f'{self.base}{path}', timeout=self.timeout, headers={
                'user-api-key': self.connection.api_key, 'Content-Type': 'application/json',
            }, **kwargs)
        except requests.RequestException as e:
            raise ChannelError(f"Channex unreachable: {e.__class__.__name__}")
        body = response.json() if response.content else {}
        if response.status_code >= 400:
            raise ChannelError(f"Channex error {response.status_code}: {str(body.get('errors', body))[:300]}")
        return body

    def update_availability(self, values):
        """values: [{room_type_id, date_from, date_to, availability}]"""
        pid = self.connection.property_id
        return self._request('POST', '/availability', json={'values': [{'property_id': pid, **v} for v in values]})

    def update_restrictions(self, values):
        """values: [{rate_plan_id, date_from, date_to, rate, stop_sell, closed_to_arrival, ...}]"""
        pid = self.connection.property_id
        return self._request('POST', '/restrictions', json={'values': [{'property_id': pid, **v} for v in values]})

    def booking_revisions(self):
        """Unacknowledged booking revisions for the property."""
        body = self._request('GET', '/booking_revisions/feed',
                             params={'filter[property_id]': self.connection.property_id})
        return body.get('data', [])

    def acknowledge(self, revision_id):
        return self._request('POST', f'/booking_revisions/{revision_id}/ack')
