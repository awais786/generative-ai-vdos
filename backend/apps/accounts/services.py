from .models import UserProfile


class CognitoService:
    @staticmethod
    def get_or_create_profile(id_token_claims: dict) -> tuple[UserProfile, bool]:
        sub = id_token_claims.get("sub", "")
        email = id_token_claims.get("email", "")
        name = id_token_claims.get("name", "")

        profile, created = UserProfile.objects.get_or_create(
            cognito_sub=sub,
            defaults={"email": email, "name": name},
        )
        if not created and (profile.email != email or profile.name != name):
            profile.email = email
            profile.name = name
            profile.save(update_fields=["email", "name", "updated_at"])

        return profile, created
