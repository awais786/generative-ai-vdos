from django import forms
from django.contrib import admin

from .models import UserAPIKey, UserProfile


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ["email", "cognito_sub", "created_at"]
    search_fields = ["email", "cognito_sub"]


class UserAPIKeyForm(forms.ModelForm):
    api_key = forms.CharField(
        widget=forms.PasswordInput(render_value=False),
        help_text="Paste the plaintext API key. It will be encrypted on save.",
        required=False,
    )

    class Meta:
        model = UserAPIKey
        fields = ["owner", "provider", "api_key", "label", "api_url"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.instance.pk:
            self.fields["api_key"].required = True
        self.fields["provider"].help_text = (
            "OpenAI → sk-... | Google → AIza... | DashScope → sk-... | Anthropic → sk-ant-..."
        )
        self.fields["api_url"].help_text = (
            "Optional workspace endpoint override — only used for DashScope."
        )

    def save(self, commit=True):
        instance = super().save(commit=False)
        plaintext = self.cleaned_data.get("api_key")
        if plaintext:
            instance.set_api_key(plaintext)
        if commit:
            instance.save()
        return instance


@admin.register(UserAPIKey)
class UserAPIKeyAdmin(admin.ModelAdmin):
    form = UserAPIKeyForm
    list_display = ["owner", "provider", "key_hint", "label", "created_at"]
    list_select_related = ["owner", "provider"]
    list_filter = ["provider"]
    search_fields = ["owner__email", "label"]
    readonly_fields = ["key_hint"]
