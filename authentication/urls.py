from django.urls import path, include
from .views import LoginView, RegistrationView

urlpatterns = [
    path('auth/register/', RegistrationView.as_view(), name= 'register'),
    path('auth/login/', LoginView.as_view(), name = 'login')
]