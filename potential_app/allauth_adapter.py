# potential_app/allauth_adapter.py

from django.conf import settings
from django import forms

from allauth.account.adapter import DefaultAccountAdapter
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from allauth.socialaccount.models import SocialApp


class NoDbAccountAdapter(DefaultAccountAdapter):
    """
    Custom ACCOUNT_ADAPTER that avoids DB lookups in clean_username().
    This prevents djongo from trying to translate SQL like
    `SELECT ... FROM auth_user WHERE username ILIKE ...`
    which is what was causing the 500 on signup.
    """

    def clean_username(self, username):
        # Basic normalization
        username = (username or "").strip()

        if not username:
            raise forms.ValidationError("Please enter a username.")

        # ⚠️ IMPORTANT:
        # We intentionally DO NOT call filter_users_by_username(username)
        # or any queryset-based existence checks here, because that triggers
        # a DB query that djongo fails to translate.
        #
        # Uniqueness is still enforced at the database level
        # via the unique constraint on the User model.
        return username


class NoDbSocialAccountAdapter(DefaultSocialAccountAdapter):
    """
    Use provider credentials from settings.SOCIALACCOUNT_PROVIDERS['<provider>']['APP']
    and do NOT query the database for SocialApp rows.

    This avoids accessing the socialaccount_socialapp* tables via djongo,
    which was causing SQLDecodeError/DatabaseError.
    """

    def list_apps(self, request, provider=None, client_id=None):
        apps = []

        providers = getattr(settings, "SOCIALACCOUNT_PROVIDERS", {})

        # If a specific provider is requested (e.g. "google")
        if provider and provider in providers:
            app_cfg = providers[provider].get("APP")
            if app_cfg:
                app = SocialApp(
                    provider=provider,
                    name=f"{provider}-app",
                    client_id=app_cfg["client_id"],
                    secret=app_cfg["secret"],
                    key=app_cfg.get("key", ""),
                )
                # We don't persist this to DB; allauth only needs the credentials
                app.pk = None
                apps.append(app)

        return apps
