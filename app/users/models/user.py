from .common import *  # noqa: F401,F403


def generate_referral_code() -> str:
    """8 belgili unique referral code generatsiya qiladi (CLAUDE.md qoidasi).

    Markaziy manba — User.save() va backfill/migration/test shundan foydalansin.
    """
    return uuid.uuid4().hex[:8].upper()


class UserManager(BaseUserManager):
    def create_user(self, phone, password=None, **extra_fields):
        if not phone:
            raise ValueError("Phone number is required.")
        extra_fields.setdefault("is_active", True)
        user = self.model(phone=phone, **extra_fields)
        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()
        user.save(using=self._db)
        return user

    def create_superuser(self, phone, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("role", User.Role.ADMIN)
        extra_fields.setdefault("admin_type", User.AdminType.SUPER)

        if extra_fields.get("is_staff") is not True:
            raise ValueError("Superuser must have is_staff=True.")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Superuser must have is_superuser=True.")

        return self.create_user(phone, password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin):
    class Role(models.TextChoices):
        PATIENT = "patient", "Patient"
        DOCTOR = "doctor", "Doctor"
        ADMIN = "admin", "Admin"

    class Sex(models.TextChoices):
        MALE = "male", "Male"
        FEMALE = "female", "Female"

    class AdminType(models.TextChoices):
        SUPER = "super", "Super"
        SIMPLE = "simple", "Simple"
        SELLER = "seller", "Seller"
        CUSTOMER_SUPPORT = "customer_support", "Customer Support"

    phone = models.CharField(max_length=15, unique=True)
    full_name = models.CharField(max_length=255, blank=True)
    role = models.CharField(max_length=10, choices=Role.choices, default=Role.PATIENT)
    active_role = models.CharField(
        max_length=10,
        choices=Role.choices,
        default=Role.PATIENT,
        help_text="Hozir qaysi sifatida ishlayapti (switch qilinadi)",
    )
    sex = models.CharField(
        max_length=10,
        choices=Sex.choices,
        null=True,
        blank=True,
    )
    birth_date = models.DateField(null=True, blank=True)
    admin_type = models.CharField(
        max_length=20, choices=AdminType.choices, null=True, blank=True
    )
    avatar = models.CharField(
        max_length=500,
        null=True,
        blank=True,
        help_text="DO Spaces key (masalan: 'avatars/5/abc123.jpg'). To'liq URL serializer'da generate_download_url orqali yaratiladi.",
    )
    referral_code = models.CharField(max_length=8, unique=True, null=True, blank=True)
    referred_by = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="referrals",
    )
    telegram_chat_id = models.BigIntegerField(null=True, blank=True, unique=True)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    date_joined = models.DateTimeField(auto_now_add=True)

    objects = UserManager()

    USERNAME_FIELD = "phone"
    REQUIRED_FIELDS = []

    class Meta:
        ordering = ["-date_joined"]

    def save(self, *args, **kwargs):
        is_new = not self.pk
        if is_new and not self.active_role:
            self.active_role = self.role

        # Doctor (asosiy yoki active rol) va Seller admin uchun referral_code
        needs_referral_code = (
            self.role == self.Role.DOCTOR
            or self.active_role == self.Role.DOCTOR
            or (
                self.role == self.Role.ADMIN
                and self.admin_type == self.AdminType.SELLER
            )
        )
        # is_active=False (soft-delete) bo'lsa referral_code'ni qayta
        # generatsiya qilmaymiz — aks holda o'chirilgan doctor'ning ref linki
        # qayta ishlab ketadi (PII tozalash niyatini buzadi).
        if not self.referral_code and needs_referral_code and self.is_active:
            self.referral_code = generate_referral_code()
            # update_fields bilan chaqirilgan bo'lsa, referral_code ham saqlansin
            update_fields = kwargs.get("update_fields")
            if update_fields is not None:
                kwargs["update_fields"] = {*update_fields, "referral_code"}

        super().save(*args, **kwargs)

        # Bitta account ham bemor, ham doctor bo'lishi mumkin — Patient har user
        # uchun "default" role-konteksti. Idempotent (get_or_create) — race
        # condition yoki retry'da xato bermaydi.
        # ATAYLAB DUBLIKAT: signals.ensure_patient_profile ham shu ishni qiladi
        # (bulk_create/migration save()'ni chetlab o'tgan holatlar uchun
        # defense-in-depth). Biri o'chirilsa ikkinchisi yagona manba bo'lib qoladi.
        if is_new:
            Patient.objects.get_or_create(user=self)

    @property
    def allowed_roles(self):
        """Foydalanuvchi qaysi rollarga switch qila oladi.

        Patient ham doctor rejimiga o'ta oladi (DoctorProfile avtomatik
        yaratiladi `switch_role` view'da, admin tasdiqlash kutiladi).
        Doctor ham bemor sifatida shifokor topa oladi. Faqat `admin` switch
        qilish admin user'larga cheklangan.
        """
        if self.role == self.Role.ADMIN:
            roles = ["admin", "doctor", "patient"]
        else:
            roles = ["doctor", "patient"]
        return roles

    @property
    def has_doctor_profile(self) -> bool:
        profile = getattr(self, "doctor_profile", None)
        # O'chirilgan (retire qilingan) doctor profili — doctor sifatida yo'q.
        return bool(profile and not profile.is_deleted)

    @property
    def is_verified_doctor(self) -> bool:
        profile = getattr(self, "doctor_profile", None)
        return bool(profile and profile.is_verified and not profile.is_deleted)

    def __str__(self):
        return self.full_name or self.phone

    @property
    def is_super_admin(self):
        return (
            self.role == self.Role.ADMIN
            and self.admin_type == self.AdminType.SUPER
        )

    @property
    def is_root_admin(self):
        """Root admin — ROOT_ADMIN_PHONE settings bilan telefon raqami mos user.

        Root hech qachon boshqalar tomonidan o'zgartirilmaydi, faqat o'zi
        super adminlarni to'liq boshqara oladi (create/delete/role change).
        """
        root_phone = getattr(settings, "ROOT_ADMIN_PHONE", "")
        return bool(root_phone) and self.phone == root_phone

    @property
    def is_seller(self):
        return (
            self.role == self.Role.ADMIN
            and self.admin_type == self.AdminType.SELLER
        )

    @property
    def is_support(self):
        return (
            self.role == self.Role.ADMIN
            and self.admin_type == self.AdminType.CUSTOMER_SUPPORT
        )


class Patient(models.Model):
    """Bemor profili — har user uchun avtomatik yaratiladi.

    User — autentifikatsiya identifikatori (phone, password, ...).
    Patient — bemor sifatida ish ko'rishish konteksti (chat, appointment,
    treatment, health monitoring kelajakda Patient.id ga ulanadi).

    Bir user bir vaqtda Patient va Doctor (DoctorProfile) bo'lishi mumkin —
    bitta phone, ikkita rol-context.
    """

    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name="patient_profile",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Patient"
        verbose_name_plural = "Patients"

    def __str__(self):
        return f"Patient #{self.id} ({self.user.phone})"
