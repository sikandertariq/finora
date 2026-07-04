from rest_framework_simplejwt.serializers import TokenObtainPairSerializer


class TenantAwareTokenObtainPairSerializer(TokenObtainPairSerializer):
    """Embed the user's tenant into the JWT so requests carry their tenant."""

    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        membership = getattr(user, "tenant_membership", None)
        if membership is not None:
            token["tenant_id"] = membership.tenant_id
        return token
