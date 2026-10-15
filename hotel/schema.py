"""
Helpers for documenting plain APIViews in the OpenAPI schema (/api/docs/).
Views built on serializers are documented automatically; views that read
request.data or query parameters directly describe them with these.
"""
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema, inline_serializer
from rest_framework import serializers

ANY = OpenApiTypes.OBJECT  # free-form JSON object


def body(name, **fields):
    """An inline request/response shape, e.g. body('MfaCode', code=serializers.CharField())."""
    return inline_serializer(name=name, fields=fields)


def query(name, description, type=str, required=False):
    return OpenApiParameter(name, type, location=OpenApiParameter.QUERY, description=description, required=required)


DATE_RANGE = [
    query('from', 'First day (YYYY-MM-DD); defaults to two weeks ago or today depending on the report'),
    query('to', 'Last day (YYYY-MM-DD)'),
    query('export', 'csv to download the rows as a spreadsheet'),
]

__all__ = ['ANY', 'DATE_RANGE', 'body', 'extend_schema', 'query', 'serializers']
