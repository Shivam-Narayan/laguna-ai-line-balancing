from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from django.contrib.auth import get_user_model

class CustomSocialAccountAdapter(DefaultSocialAccountAdapter):
    def pre_social_login(self, request, sociallogin):
        # If the user is already connected/logged in, do nothing
        if sociallogin.is_existing:
            return
            
        user_model = get_user_model()
        email = sociallogin.user.email
        
        # If the Google account has an email, let's check our local DB
        if email:
            try:
                # Find if we already have a user with this email
                existing_user = user_model.objects.get(email__iexact=email)
                
                # Automatically connect the Google social account to the existing local user!
                sociallogin.connect(request, existing_user)
            except user_model.DoesNotExist:
                # No existing user found. It will create a new one normally.
                pass
    def populate_user(self, request, sociallogin, data):
        user = super().populate_user(request, sociallogin, data)
        
        # Populate the custom 'username' field from Google's 'name' or email prefix
        if not getattr(user, 'username', None):
            name = data.get('name') or f"{data.get('first_name', '')} {data.get('last_name', '')}".strip()
            if name:
                user.username = name
            elif user.email:
                user.username = user.email.split('@')[0]
            else:
                user.username = "Unknown User"
                
        return user
