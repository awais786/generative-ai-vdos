from .models import UserProfile


class CognitoService:
    @staticmethod
    def get_or_create_profile(id_token_claims: dict) -> tuple[UserProfile, bool]:
        sub = id_token_claims.get("sub", "")
        email = id_token_claims.get("email", "")
        name = id_token_claims.get("name")  # None when claim is absent

        profile, created = UserProfile.objects.get_or_create(
            cognito_sub=sub,
            defaults={"email": email, "name": name or ""},
        )
        if not created:
            update_fields = []
            if profile.email != email:
                profile.email = email
                update_fields.append("email")
            if name is not None and profile.name != name:
                profile.name = name
                update_fields.append("name")
            if update_fields:
                profile.save(update_fields=[*update_fields, "updated_at"])

        return profile, created
