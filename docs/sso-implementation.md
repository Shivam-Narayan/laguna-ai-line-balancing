# Google SSO Implementation Guide

This document outlines the complete Single Sign-On (SSO) architecture and implementation details for Laguna AI using Google OAuth 2.0, `django-allauth`, and `dj-rest-auth`.

## Overview
The backend integrates with Google's OAuth 2.0 framework to allow users to securely log into the application using their Google accounts. The flow ensures that the frontend only ever receives the standard Django JWT (`access_token` and `refresh_token`), maintaining a unified authentication state whether a user logs in via Email/Password or via Google SSO.

### Tech Stack
* **Provider:** Google Workspace / Google Accounts
* **Backend Libraries:** `django-allauth`, `dj-rest-auth`
* **Frontend Compatibility:** React, Vite (port 5173)

---

## 1. Backend Configuration

### Dependencies
The following packages were added to `backend/requirements.txt`:
* `django-allauth`
* `dj-rest-auth`

### `settings.py` Setup
The following critical components were added to `backend/config/settings.py`:

**Installed Apps:**
```python
INSTALLED_APPS = [
    # ...
    'django.contrib.sites',
    'allauth',
    'allauth.account',
    'allauth.socialaccount',
    'allauth.socialaccount.providers.google',
    'dj_rest_auth',
    'dj_rest_auth.registration',
]
```

**Provider Configuration:**
This maps the environment variables to the `allauth` Google provider setup.
```python
GOOGLE_CLIENT_ID = os.getenv('GOOGLE_CLIENT_ID')
GOOGLE_CLIENT_SECRET = os.getenv('GOOGLE_CLIENT_SECRET')

SOCIALACCOUNT_PROVIDERS = {
    'google': {
        'APP': {
            'client_id': GOOGLE_CLIENT_ID,
            'secret': GOOGLE_CLIENT_SECRET,
            'key': '',
        },
        'SCOPE': ['profile', 'email'],
        'AUTH_PARAMS': {'access_type': 'online'}
    }
}
```

### API View
A dedicated class-based view was created in `backend/apps/accounts/views.py` to handle the specific Google OAuth adapter logic and specify the strict callback URL that Google expects.

```python
from allauth.socialaccount.providers.google.views import GoogleOAuth2Adapter
from allauth.socialaccount.providers.oauth2.client import OAuth2Client
from dj_rest_auth.registration.views import SocialLoginView

class GoogleLoginView(SocialLoginView):
    adapter_class = GoogleOAuth2Adapter
    client_class = OAuth2Client
    callback_url = getattr(settings, 'DEV_FRONTED_URL', 'http://localhost:5173') + '/auth/callback/google'
```

### URL Routing
The view is exposed in `backend/config/urls.py`:
```python
path('api/auth/google/', GoogleLoginView.as_view(), name='google_login'),
```

---

## 2. Google Cloud Console Setup

To generate the required Client ID and Secret, the following configuration was applied in the [Google Cloud Console](https://console.cloud.google.com/):

1. **OAuth Consent Screen:** Configured as `External` (or `Internal` for Google Workspace organizations).
2. **Credentials -> OAuth Client ID:**
   * **Type:** Web Application
   * **Authorized redirect URIs:** 
     * `http://localhost:5173/auth/callback/google` (For Vite Frontend)
     * `https://developers.google.com/oauthplayground` (For Backend Testing)

---

## 3. Environment Variables

The backend relies on the hidden `.env` file to securely store these credentials:

```env
GOOGLE_CLIENT_ID=your-google-client-id
GOOGLE_CLIENT_SECRET=your-google-client-secret
```

*Note: Any time the dependencies or database schema changes for `allauth`, `python manage.py migrate` and `uv pip install -r requirements.txt` must be run.*

---

## 4. Testing the Backend Directly (Without React)

To verify the backend configuration without writing frontend code, you can use the Google OAuth 2.0 Playground and Postman.

### Step A: Get a Google Token
1. Go to [Google OAuth 2.0 Playground](https://developers.google.com/oauthplayground/).
2. Click the **Gear Icon** (top right) -> Check **"Use your own OAuth credentials"**.
3. Input your `Client ID` and `Client Secret`.
4. Under Step 1, manually input the scopes: `email profile` and click **Authorize APIs**.
5. Log into your Google Account.
6. Under Step 2, click **Exchange authorization code for tokens**.
7. Copy the `Access token` (Starts with `ya29.`).

### Step B: Hit the Django Endpoint
1. Open Postman.
2. Create a `POST` request to `http://localhost:8000/api/auth/google/`.
3. Set the Body to `raw` -> `JSON`.
4. Payload:
   ```json
   {
       "access_token": "ya29.your_copied_token_here"
   }
   ```
5. **Expected Result:** `200 OK`. The user will be created in the Django DB, and the response headers will contain the standard JWT `access_token` and `refresh_token` secure cookies.

---

## 5. Frontend Integration (Next Steps)

For the frontend team using React/Vite, the implementation requires utilizing the `@react-oauth/google` library.

1. **Install Library:** `npm install @react-oauth/google`
2. **Provider Wrapper:** Wrap the application (`App.jsx` or `main.jsx`) in the context provider:
   ```jsx
   import { GoogleOAuthProvider } from '@react-oauth/google';
   
   <GoogleOAuthProvider clientId="YOUR_GOOGLE_CLIENT_ID">
       <App />
   </GoogleOAuthProvider>
   ```
3. **Login Component:** Use the `useGoogleLogin` hook to handle the popup flow and retrieve the token.
   ```jsx
   import { useGoogleLogin } from '@react-oauth/google';

   const login = useGoogleLogin({
     onSuccess: async (tokenResponse) => {
       // 1. Get the Google token
       const googleToken = tokenResponse.access_token;
       
       // 2. Send it to Django
       const res = await axios.post('http://localhost:8000/api/auth/google/', {
           access_token: googleToken
       });
       
       // 3. Django sets the JWT cookies securely. Redirect user!
       if (res.status === 200) {
           navigate('/user-dashboard');
       }
     },
   });

   <button onClick={() => login()}>Sign in with Google</button>
   ```
