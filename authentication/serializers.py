from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from django.contrib.auth import authenticate
from rest_framework_simplejwt.tokens import RefreshToken
from .models import User

class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['id', 'email', 'first_name', 'last_name']
        read_only_fields = ['id']

class RegistrationSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True)

    class Meta:
        model = User
        # fields = ['']  # include all fields from the User model
        exclude = ['groups', 'user_permissions']

    def create(self, validated_data):
        # Extract password to hash it
        password = validated_data.pop('password')
        user = User.objects.create_user(password=password, **validated_data)
        return user     
    
    
class LoginSerializer(TokenObtainPairSerializer):
        
    def validate(self, attrs):
        # The default result (access/refresh tokens)
        data = super().validate(attrs)
        
        # Add extra responses here
        data['user'] = UserSerializer(self.user).data
        
        return data