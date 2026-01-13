from django.shortcuts import render
from rest_framework_simplejwt.views import TokenObtainPairView
from .serializers import LoginSerializer, RegistrationSerializer
from rest_framework.generics import CreateAPIView
# Create your views here.



class RegistrationView(CreateAPIView):
    serializer_class = RegistrationSerializer
    
class LoginView(TokenObtainPairView):
    serializer_class = LoginSerializer