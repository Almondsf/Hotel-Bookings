from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

from .models import User, normalize_email
from .permissions import can_assign_role, capabilities_for


class UserSerializer(serializers.ModelSerializer):
    """The signed-in user, including what they are allowed to do (for the UI)."""
    capabilities = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ['id', 'email', 'first_name', 'last_name', 'phone', 'role', 'capabilities',
                  'mfa_enabled', 'mfa_required']
        read_only_fields = fields

    mfa_required = serializers.BooleanField(read_only=True)

    def get_capabilities(self, obj):
        return capabilities_for(obj)


class LoginSerializer(TokenObtainPairSerializer):
    def validate(self, attrs):
        attrs[self.username_field] = normalize_email(attrs.get(self.username_field))
        data = super().validate(attrs)
        data['user'] = UserSerializer(self.user).data
        return data


class LogoutSerializer(serializers.Serializer):
    refresh = serializers.CharField(required=False, help_text="Omit when using the refresh cookie")


class ChangePasswordSerializer(serializers.Serializer):
    current_password = serializers.CharField(style={'input_type': 'password'})
    new_password = serializers.CharField(style={'input_type': 'password'})

    def validate_current_password(self, value):
        if not self.context['request'].user.check_password(value):
            raise serializers.ValidationError("Current password is incorrect.")
        return value

    def validate(self, data):
        validate_password(data['new_password'], self.context['request'].user)
        return data


class PasswordResetRequestSerializer(serializers.Serializer):
    email = serializers.EmailField()

    def validate_email(self, value):
        return normalize_email(value)


class PasswordResetConfirmSerializer(serializers.Serializer):
    uid = serializers.CharField()
    token = serializers.CharField()
    new_password = serializers.CharField(style={'input_type': 'password'})

    def validate(self, data):
        from .services import user_from_reset_token

        user = user_from_reset_token(data['uid'], data['token'])
        if user is None:
            raise serializers.ValidationError({"token": "This link is invalid or has expired."})
        validate_password(data['new_password'], user)
        data['user'] = user
        return data


class StaffSerializer(serializers.ModelSerializer):
    """
    Staff accounts as seen by managers. Accounts are created without a
    password; the new member sets one through the emailed invite link.
    """

    class Meta:
        model = User
        fields = [
            'id', 'email', 'first_name', 'last_name', 'phone', 'role',
            'is_active', 'date_joined', 'last_login', 'mfa_enabled',
        ]
        read_only_fields = ['id', 'is_active', 'date_joined', 'last_login', 'mfa_enabled']
        extra_kwargs = {'role': {'required': True}}

    def validate_email(self, value):
        value = normalize_email(value)
        queryset = User.objects.filter(email=value)
        if self.instance is not None:
            queryset = queryset.exclude(pk=self.instance.pk)
        if queryset.exists():
            raise serializers.ValidationError("A user with this email already exists.")
        return value

    def validate_role(self, value):
        if not can_assign_role(self.context['request'].user, value):
            raise serializers.ValidationError("You are not allowed to assign this role.")
        return value

    def create(self, validated_data):
        return User.objects.create_user(password=None, **validated_data)
