from django.urls import path
from rest_framework.routers import SimpleRouter

from .views import (
    ChangePasswordView,
    LoginView,
    LogoutView,
    MeView,
    MfaDisableView,
    MfaEnableView,
    MfaLoginView,
    MfaSetupView,
    PasswordResetConfirmView,
    PasswordResetRequestView,
    RefreshView,
    StaffViewSet,
)

router = SimpleRouter()
router.register('staff', StaffViewSet, basename='staff')

urlpatterns = [
    path('auth/login/', LoginView.as_view(), name='login'),
    path('auth/login/mfa/', MfaLoginView.as_view(), name='login-mfa'),
    path('auth/mfa/setup/', MfaSetupView.as_view(), name='mfa-setup'),
    path('auth/mfa/enable/', MfaEnableView.as_view(), name='mfa-enable'),
    path('auth/mfa/disable/', MfaDisableView.as_view(), name='mfa-disable'),
    path('auth/refresh/', RefreshView.as_view(), name='token-refresh'),
    path('auth/logout/', LogoutView.as_view(), name='logout'),
    path('auth/me/', MeView.as_view(), name='me'),
    path('auth/change-password/', ChangePasswordView.as_view(), name='change-password'),
    path('auth/password-reset/', PasswordResetRequestView.as_view(), name='password-reset'),
    path('auth/password-reset/confirm/', PasswordResetConfirmView.as_view(), name='password-reset-confirm'),
    *router.urls,
]
