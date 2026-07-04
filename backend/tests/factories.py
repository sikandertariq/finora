import factory
from django.contrib.auth.models import User

from apps.tenancy.models import Tenant


class TenantFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Tenant

    name = factory.Sequence(lambda n: f"Tenant {n}")
    slug = factory.Sequence(lambda n: f"tenant-{n}")


class UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = User

    username = factory.Sequence(lambda n: f"user{n}")
