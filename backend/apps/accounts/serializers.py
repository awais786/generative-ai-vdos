from rest_framework import serializers
from .models import UserAPIKey, UserProfile


class UserProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserProfile
        fields = ["id", "cognito_sub", "email", "name", "created_at", "updated_at"]
        read_only_fields = ["id", "cognito_sub", "created_at", "updated_at"]


class UserAPIKeySerializer(serializers.ModelSerializer):
    api_key = serializers.CharField(write_only=True, min_length=8)

    class Meta:
        model = UserAPIKey
        fields = ["id", "provider", "api_key", "key_hint", "label", "api_url", "created_at"]
        read_only_fields = ["id", "key_hint", "created_at"]

    def get_extra_kwargs(self):
        kwargs = super().get_extra_kwargs()
        if self.instance is not None:
            kwargs.setdefault("provider", {})["read_only"] = True
        return kwargs

    def create(self, validated_data):
        plaintext = validated_data.pop("api_key")
        instance = UserAPIKey(**validated_data)
        instance.set_api_key(plaintext)
        instance.save()
        return instance

    def update(self, instance, validated_data):
        plaintext = validated_data.pop("api_key", None)
        update_fields = ["updated_at"]
        if plaintext:
            instance.set_api_key(plaintext)
            update_fields += ["_api_key_enc", "key_hint"]
        if "label" in validated_data:
            instance.label = validated_data["label"]
            update_fields.append("label")
        if "api_url" in validated_data:
            instance.api_url = validated_data["api_url"]
            update_fields.append("api_url")
        instance.save(update_fields=update_fields)
        return instance
