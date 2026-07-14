import os
from typing import Dict, Any

from django.conf import settings
from rest_framework import serializers  # type:ignore
from django.core.mail import send_mail
from django.utils.html import strip_tags
from django.contrib.auth import get_user_model
from django.utils.crypto import get_random_string
from django.template.loader import render_to_string
from apps.accounts.utils.validators import validate_password, validate_email

from apps.accounts.models import PasswordResetToken, User

DEV_FRONTED_URL = os.getenv('DEV_FRONTED_URL')
PRODUCTION_FRONTED_URL = os.getenv('PRODUCTION_FRONTED_URL')
ENVIRONMENT = os.getenv('ENVIRONMENT')

User = get_user_model()


class UserSerializer(serializers.ModelSerializer):
    email = serializers.EmailField(validators=[validate_email])

    class Meta:
        model = User
        fields = ['id', 'username', 'email', 'phonenumber', 'location', 'department',
                  'user_type', 'status', 'latitude', 'longitude', 'created_at', 'send_mail']
        extra_kwargs = {
            'password': {'write_only': True},
        }


class RegisterUserSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=150)
    email = serializers.EmailField(validators=[validate_email])
    password = serializers.CharField(write_only=True, min_length=8, required=True)
    phonenumber = serializers.CharField(required=False, allow_blank=True)
    location = serializers.CharField(required=False, allow_blank=True)
    department = serializers.CharField(required=False, allow_blank=True)
    user_type = serializers.IntegerField(default=0)
    status = serializers.BooleanField(default=True)
    latitude = serializers.FloatField(required=False)
    longitude = serializers.FloatField(required=False)
    send_mail = serializers.BooleanField(required=False, allow_null=True, default=False)

    def validate_email(self, value: str) -> str:

        validate_email(value)

        if User.objects.filter(email=value.lower()).exists():
            raise serializers.ValidationError("A user with this email already exists.")

        return value

    def validate_password(self, value: str) -> str:
        validate_password(value)
        return value

    def create(self, validated_data: Dict[str, Any]) -> Any:
        """
        Creating a new user with the validated data.
        """
        user = User.objects.create_user(
            username=validated_data['username'],
            email=validated_data['email'].lower(),
            password=validated_data['password'],
            phonenumber=validated_data.get('phonenumber'),
            location=validated_data.get('location'),
            department=validated_data.get('department'),
            user_type=validated_data.get('user_type'),
            status=validated_data.get('status'),
            latitude=validated_data.get('latitude'),
            longitude=validated_data.get('longitude'),
            send_mail=validated_data.get('send_mail'),
        )

        return user


class UpdateUserSerializer(serializers.Serializer):
    email = serializers.EmailField(validators=[validate_email])
    phonenumber = serializers.CharField(required=False, allow_blank=True)
    location = serializers.CharField(required=False, allow_blank=True)
    department = serializers.CharField(required=False, allow_blank=True)
    user_type = serializers.IntegerField(default=0)
    status = serializers.BooleanField(default=True)
    latitude = serializers.FloatField(required=False)
    longitude = serializers.FloatField(required=False)
    created_at = serializers.DateTimeField(read_only=True)
    send_mail = serializers.BooleanField(required=False, allow_null=True, default=False)

    def validate_email(self, value: str) -> str:
        validate_email(value)
        if self.instance and User.objects.filter(email=value.lower()).exclude(id=self.instance.id).exists():
            raise serializers.ValidationError("A user with this email already exists.")
        return value

    def update(self, instance: Any, validated_data: Dict[str, Any]) -> Any:
        for field, value in validated_data.items():
            if field == "email":
                if value.lower() != instance.email.lower():
                    if User.objects.filter(email=value.lower()).exclude(id=instance.id).exists():
                        raise serializers.ValidationError({"email": "A user with this email already exists."})
                    validate_email(value)
                    value = value.lower()
                setattr(instance, field, value)
            elif field == "username" or field == "created_at":
                continue
            else:
                setattr(instance, field, value)
        instance.save()
        return instance


# send grid serialization
class RequestPasswordResetSerializer(serializers.Serializer):
    email = serializers.EmailField()

    def validate_email(self, value: str) -> str:
        # We do NOT check if the user exists here to prevent username enumeration.
        return value.lower()

    def save(self) -> Dict[str, str]:
        email = self.validated_data['email']
        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            # Standard Security Practice: Silently succeed so attackers cannot
            # use the forgot password endpoint to guess valid emails.
            return {"email": email}

        token = get_random_string(length=32)
        PasswordResetToken.objects.create(user=user, token=token)

        base_url = (
            DEV_FRONTED_URL
            if ENVIRONMENT == 'development'
            else PRODUCTION_FRONTED_URL
        )

        # Send the password reset email
        reset_link = f"{base_url}/forgot-password?token={token}"

        # Render the email template
        subject = "Password Reset Request"
        html_message = render_to_string('password_reset_email.html', {'reset_link': reset_link, 'user': user})
        plain_message = strip_tags(html_message)

        send_mail(
            subject=subject,
            message=plain_message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
            html_message=html_message,
            fail_silently=False,
        )
        return {"email": user.email}


class ResetPasswordSerializer(serializers.Serializer):
    token = serializers.CharField()
    new_password = serializers.CharField(write_only=True)
    confirm_password = serializers.CharField(write_only=True)

    def validate(self, data: Dict[str, Any]) -> Dict[str, Any]:
        token = data.get('token')
        new_password = data.get('new_password')
        confirm_password = data.get('confirm_password')

        if new_password != confirm_password:
            raise serializers.ValidationError({"error": "Passwords do not match"})

        if new_password and confirm_password:
            validate_password(new_password)
            validate_password(confirm_password)

        try:
            reset_token = PasswordResetToken.objects.get(token=token)
            if reset_token.is_expired():
                raise serializers.ValidationError({"error": "Token has expired"})
            self.context['reset_token'] = reset_token  # Store reset token for later use
        except PasswordResetToken.DoesNotExist:
            raise serializers.ValidationError({"error": "Invalid reset token"})

        return data

    def save(self) -> Dict[str, str]:
        reset_token = self.context['reset_token']
        user = reset_token.user
        user.set_password(self.validated_data['new_password'])
        user.save()

        # Delete the token after successful reset
        reset_token.delete()

        return {"message": "Your password has been reset successfully."}

