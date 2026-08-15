import factory
from django.contrib.auth import get_user_model

User = get_user_model()


class UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = User

    phone = factory.Sequence(lambda n: f"99890000{n:04d}")
    full_name = factory.Faker("name")
    role = "patient"

    @classmethod
    def create_patient(cls, **kwargs):
        return cls.create(role="patient", **kwargs)

    @classmethod
    def create_doctor(cls, **kwargs):
        kwargs.setdefault("active_role", "doctor")
        user = cls.create(role="doctor", **kwargs)
        user.referral_code = f"DOC{user.id:05d}"
        user.save(update_fields=["referral_code"])
        return user

    @classmethod
    def create_admin(cls, admin_type="super", **kwargs):
        return cls.create(role="admin", admin_type=admin_type, is_staff=True, **kwargs)

    @classmethod
    def create_seller(cls, **kwargs):
        user = cls.create_admin(admin_type="seller", **kwargs)
        user.referral_code = f"SEL{user.id:05d}"
        user.save(update_fields=["referral_code"])
        return user
