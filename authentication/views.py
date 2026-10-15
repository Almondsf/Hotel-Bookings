from django.conf import settings
from django.db import transaction
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import AuthenticationFailed, PermissionDenied
from rest_framework.generics import GenericAPIView
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.serializers import TokenRefreshSerializer
from rest_framework_simplejwt.views import TokenObtainPairView

from audit.models import AuditLog
from audit.services import record
from hotel.schema import ANY, DATE_RANGE, body, extend_schema, query, serializers as s

from . import mfa
from .models import User, normalize_email
from .permissions import HasCapability, can_manage_user
from .serializers import (
    ChangePasswordSerializer,
    LoginSerializer,
    LogoutSerializer,
    PasswordResetConfirmSerializer,
    PasswordResetRequestSerializer,
    StaffSerializer,
    UserSerializer,
)
from .services import revoke_all_sessions, send_password_reset, send_staff_invite
from .throttles import EmailThrottle, LoginIPThrottle


# Browser clients keep the refresh token in an httpOnly cookie (unreadable by
# JavaScript, so an XSS bug can't steal a long-lived session) and only the
# short-lived access token in memory. They opt in with this header; API and
# mobile clients get the refresh token in the response body as usual.
REFRESH_COOKIE = 'hotel_refresh'
COOKIE_MODE_HEADER = 'HTTP_X_AUTH_MODE'


def wants_cookie(request):
    return request.META.get(COOKIE_MODE_HEADER) == 'cookie'


def with_refresh_cookie(response, data):
    response.set_cookie(
        REFRESH_COOKIE, data['refresh'],
        max_age=int(settings.SIMPLE_JWT['REFRESH_TOKEN_LIFETIME'].total_seconds()),
        httponly=True, secure=not settings.DEBUG, samesite='Strict', path='/api/auth/',
    )
    response.data = {k: v for k, v in data.items() if k != 'refresh'}
    return response


class LoginView(TokenObtainPairView):
    serializer_class = LoginSerializer
    throttle_classes = [LoginIPThrottle, EmailThrottle]
    login_ip_throttle_scope = 'login_ip'
    email_throttle_scope = 'login_email'

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        try:
            serializer.is_valid(raise_exception=True)
        except AuthenticationFailed:
            email = request.data.get('email')
            record(AuditLog.Action.LOGIN_FAILED, request=request,
                   actor_email=normalize_email(email if isinstance(email, str) else ''))
            raise
        user = serializer.user
        if user.mfa_enabled:
            # Password was right; tokens only after the second factor
            return Response({'mfa_required': True, 'mfa_ticket': mfa.make_ticket(user)})
        record(AuditLog.Action.LOGIN_SUCCEEDED, request=request, actor=user)
        return session_response(request, user)


def session_response(request, user):
    """Issue access + refresh tokens (refresh in a cookie for browsers)."""
    from django.contrib.auth.models import update_last_login

    refresh = RefreshToken.for_user(user)
    update_last_login(None, user)
    data = {'refresh': str(refresh), 'access': str(refresh.access_token), 'user': UserSerializer(user).data}
    response = Response(data, status=status.HTTP_200_OK)
    return with_refresh_cookie(response, data) if wants_cookie(request) else response


class MfaLoginView(APIView):
    """Second sign-in step: the ticket from the password step plus an authenticator or recovery code."""
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [LoginIPThrottle]
    login_ip_throttle_scope = 'login_ip'

    @extend_schema(summary='Sign in, step 2: two-factor code', request=body('MfaLogin', mfa_ticket=s.CharField(), code=s.CharField(required=False), recovery_code=s.CharField(required=False)), responses=ANY)
    def post(self, request):
        user = mfa.user_from_ticket(str(request.data.get('mfa_ticket', '')))
        if user is None:
            return Response({'detail': 'Sign-in expired. Please start again.'}, status=status.HTTP_401_UNAUTHORIZED)
        code = str(request.data.get('code', ''))
        recovery = str(request.data.get('recovery_code', ''))
        if not (mfa.verify_code(user, code) if code else recovery and mfa.use_recovery_code(user, recovery)):
            record(AuditLog.Action.LOGIN_FAILED, request=request, actor_email=user.email, changes={'step': 'mfa'})
            return Response({'code': ['That code is not valid.']}, status=status.HTTP_400_BAD_REQUEST)
        record(AuditLog.Action.LOGIN_SUCCEEDED, request=request, actor=user,
               changes={'mfa': 'recovery_code' if recovery and not code else 'totp'})
        return session_response(request, user)


class MfaSetupView(APIView):
    """POST: start enrolment (secret + otpauth URI for the authenticator app)."""
    permission_classes = [IsAuthenticated]

    @extend_schema(summary='Start two-factor enrolment', request=None, responses=body('MfaSetup', secret=s.CharField(), otpauth_uri=s.CharField()))
    def post(self, request):
        if request.user.mfa_enabled:
            return Response({'error': 'Two-factor sign-in is already on.'}, status=status.HTTP_409_CONFLICT)
        secret, uri = mfa.start_enrolment(request.user)
        return Response({'secret': secret, 'otpauth_uri': uri})


class MfaEnableView(APIView):
    """POST {code}: confirm enrolment; returns recovery codes, shown only this once."""
    permission_classes = [IsAuthenticated]

    @extend_schema(summary='Confirm two-factor enrolment', request=body('MfaEnable', code=s.CharField()), responses=body('MfaRecoveryCodes', recovery_codes=s.ListField(child=s.CharField())))
    def post(self, request):
        codes = mfa.confirm_enrolment(request.user, str(request.data.get('code', '')))
        if codes is None:
            return Response({'code': ['That code is not valid. Check the time on your phone.']},
                            status=status.HTTP_400_BAD_REQUEST)
        record(AuditLog.Action.MFA_CHANGED, request=request, target=request.user, changes={'enabled': True})
        return Response({'recovery_codes': codes})


class MfaDisableView(APIView):
    """POST {password}: turn two-factor off (not allowed where the role requires it)."""
    permission_classes = [IsAuthenticated]

    @extend_schema(summary='Turn two-factor sign-in off', request=body('MfaDisable', password=s.CharField()), responses=ANY)
    def post(self, request):
        user = request.user
        if not user.check_password(str(request.data.get('password', ''))):
            return Response({'password': ['Incorrect password.']}, status=status.HTTP_400_BAD_REQUEST)
        if user.mfa_required:
            return Response({'error': 'Your role requires two-factor sign-in.'}, status=status.HTTP_403_FORBIDDEN)
        mfa.disable(user)
        record(AuditLog.Action.MFA_CHANGED, request=request, target=user, changes={'enabled': False})
        return Response({'detail': 'Two-factor sign-in turned off.'})


class RefreshView(GenericAPIView):
    """Exchange a refresh token (body or cookie) for a new access token; the refresh token rotates."""
    permission_classes = [AllowAny]
    authentication_classes = []
    serializer_class = TokenRefreshSerializer
    throttle_classes = [LoginIPThrottle]
    # Not the login budget: page reloads refresh, and sharing it locked staff out after a few clicks
    login_ip_throttle_scope = 'token_refresh'

    def post(self, request):
        from_cookie = 'refresh' not in request.data
        token = request.COOKIES.get(REFRESH_COOKIE, '') if from_cookie else request.data['refresh']
        serializer = self.get_serializer(data={'refresh': token})
        try:
            if not token:
                raise AuthenticationFailed("No session")
            serializer.is_valid(raise_exception=True)
        except (TokenError, AuthenticationFailed):
            # 401 (not 403) so clients know to sign in again
            return Response({"detail": "Session expired. Please sign in again."}, status=status.HTTP_401_UNAUTHORIZED)
        response = Response(serializer.validated_data)
        return with_refresh_cookie(response, serializer.validated_data) if from_cookie else response


class LogoutView(GenericAPIView):
    """Revoke the given refresh token. Access tokens expire on their own shortly."""
    serializer_class = LogoutSerializer
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        raw = serializer.validated_data.get('refresh') or request.COOKIES.get(REFRESH_COOKIE, '')
        try:
            token = RefreshToken(raw)
            if str(token['user_id']) != str(request.user.pk):
                raise TokenError("Token does not belong to this user")
            token.blacklist()
        except TokenError:
            return Response({"error": "Invalid or expired refresh token."}, status=status.HTTP_400_BAD_REQUEST)
        record(AuditLog.Action.LOGOUT, request=request)
        response = Response(status=status.HTTP_205_RESET_CONTENT)
        response.delete_cookie(REFRESH_COOKIE, path='/api/auth/', samesite='Strict')
        return response


class MeView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(summary='The signed-in user and their capabilities', responses=UserSerializer)
    def get(self, request):
        return Response(UserSerializer(request.user).data)


class ChangePasswordView(GenericAPIView):
    serializer_class = ChangePasswordSerializer
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = request.user
        with transaction.atomic():
            user.set_password(serializer.validated_data['new_password'])
            user.save(update_fields=['password'])
            revoke_all_sessions(user)
        record(AuditLog.Action.PASSWORD_CHANGED, request=request)
        return Response({"detail": "Password changed. Please sign in again."})


class PasswordResetRequestView(GenericAPIView):
    """Always answers the same way, so it can't be used to discover staff emails."""
    serializer_class = PasswordResetRequestSerializer
    permission_classes = [AllowAny]
    throttle_classes = [LoginIPThrottle, EmailThrottle]
    login_ip_throttle_scope = 'login_ip'
    email_throttle_scope = 'password_reset_email'

    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data['email']
        user = User.objects.filter(email=email, is_active=True).first()
        if user is not None:
            send_password_reset(user)
        record(AuditLog.Action.PASSWORD_RESET_REQUESTED, request=request, actor=user, actor_email=email)
        return Response({"detail": "If that email belongs to an active account, a reset link has been sent."})


class PasswordResetConfirmView(GenericAPIView):
    """Sets a password from an emailed link. Used for both invites and resets."""
    serializer_class = PasswordResetConfirmSerializer
    permission_classes = [AllowAny]
    throttle_classes = [LoginIPThrottle]
    login_ip_throttle_scope = 'login_ip'

    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.validated_data['user']
        with transaction.atomic():
            user.set_password(serializer.validated_data['new_password'])  # also invalidates the link
            user.save(update_fields=['password'])
            revoke_all_sessions(user)
        record(AuditLog.Action.PASSWORD_RESET_COMPLETED, request=request, actor=user)
        return Response({"detail": "Password set. You can now sign in."})


class StaffViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.CreateModelMixin,
                   mixins.UpdateModelMixin, viewsets.GenericViewSet):
    """
    Staff management. Accounts are never deleted (the audit trail and, later,
    folios and shifts reference them); deactivate them instead.
    """
    serializer_class = StaffSerializer
    permission_classes = [HasCapability('staff.manage')]
    http_method_names = ['get', 'post', 'patch', 'head', 'options']

    def get_queryset(self):
        queryset = User.objects.order_by('first_name', 'last_name', 'id')
        role = self.request.query_params.get('role')
        if role:
            queryset = queryset.filter(role=role)
        is_active = self.request.query_params.get('is_active')
        if is_active in ('true', 'false'):
            queryset = queryset.filter(is_active=is_active == 'true')
        return queryset

    def _check_can_manage(self, target):
        if not can_manage_user(self.request.user, target):
            raise PermissionDenied("You are not allowed to manage this account.")

    def perform_create(self, serializer):
        user = serializer.save()
        record(AuditLog.Action.STAFF_INVITED, request=self.request, target=user, changes={'role': user.role})
        send_staff_invite(user, invited_by=self.request.user)

    def perform_update(self, serializer):
        target = serializer.instance
        self._check_can_manage(target)
        before = {field: getattr(target, field) for field in serializer.validated_data}
        user = serializer.save()
        changes = {
            field: {'from': before[field], 'to': getattr(user, field)}
            for field in before if before[field] != getattr(user, field)
        }
        if changes:
            record(AuditLog.Action.STAFF_UPDATED, request=self.request, target=user, changes=changes)
            if 'role' in changes or 'email' in changes:
                # Sessions were issued under the old identity/role
                revoke_all_sessions(user)

    @action(detail=True, methods=['post'])
    def deactivate(self, request, pk=None):
        user = self.get_object()
        self._check_can_manage(user)
        with transaction.atomic():
            user.is_active = False
            user.save(update_fields=['is_active'])
            revoke_all_sessions(user)
        record(AuditLog.Action.STAFF_DEACTIVATED, request=request, target=user)
        return Response(self.get_serializer(user).data)

    @action(detail=True, methods=['post'])
    def reactivate(self, request, pk=None):
        user = self.get_object()
        self._check_can_manage(user)
        user.is_active = True
        user.save(update_fields=['is_active'])
        record(AuditLog.Action.STAFF_REACTIVATED, request=request, target=user)
        return Response(self.get_serializer(user).data)

    @action(detail=True, methods=['post'], url_path='reset-mfa')
    def reset_mfa(self, request, pk=None):
        """Lost phone and recovery codes: clear two-factor so the person can enrol again."""
        user = self.get_object()
        self._check_can_manage(user)
        mfa.disable(user)
        revoke_all_sessions(user)
        record(AuditLog.Action.MFA_CHANGED, request=request, target=user, changes={'reset_by_manager': True})
        return Response(self.get_serializer(user).data)

    @action(detail=True, methods=['post'], url_path='resend-invite')
    def resend_invite(self, request, pk=None):
        user = self.get_object()
        self._check_can_manage(user)
        if user.has_usable_password():
            return Response({"error": "This user has already set a password."}, status=status.HTTP_400_BAD_REQUEST)
        send_staff_invite(user, invited_by=request.user)
        return Response({"detail": "Invite sent."})
