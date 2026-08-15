from .common import *  # noqa: F401,F403
from .common import _patient_profile_id_for  # underscore (star bermaydi)


class DietProfile(models.Model):
    """Bemorning parhez profili — onboarding'da yig'iladi, target hisobiga asos.

    YAGONA MANBA qoidasi: jins/yosh — User (sex/birth_date); bo'y/vazn/kasalliklar —
    MedicalCard/MedicalCondition. Bu yerda faqat maqsad va turmush tarzi saqlanadi.
    """

    class Goal(models.TextChoices):
        LOSE = "lose", "Ozish"
        GAIN = "gain", "Vazn yig'ish"
        MUSCLE = "muscle", "Muskul chiqarish"
        CONDITION = "condition", "Kasallik nazorati"
        MAINTAIN = "maintain", "Sog'lom ovqatlanish"

    class Activity(models.TextChoices):
        SEDENTARY = "sedentary", "O'tirib ishlash"
        LIGHT = "light", "Yengil"
        MODERATE = "moderate", "O'rtacha"
        HIGH = "high", "Yuqori"
        VERY_HIGH = "very_high", "Juda yuqori"

    class Meals(models.TextChoices):
        TWO = "two", "2 mahal"
        THREE = "three", "3 mahal"
        THREE_SNACK = "three_snack", "3 mahal + gazak"
        FOUR = "four", "4 mahal"
        FIVE_PLUS = "five_plus", "5+"

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="diet_profile",
    )
    patient_profile = models.OneToOneField(
        "users.Patient",
        on_delete=models.CASCADE,
        related_name="diet_profile",
        null=True,
        blank=True,
    )
    goal = models.CharField(max_length=12, choices=Goal.choices, default=Goal.MAINTAIN)
    target_weight_kg = models.DecimalField(
        max_digits=5, decimal_places=1, null=True, blank=True
    )
    pace_kg_week = models.DecimalField(
        max_digits=3, decimal_places=2, null=True, blank=True,
        help_text="0.25 / 0.5 / 0.75, maks 1.0",
    )
    activity_level = models.CharField(
        max_length=10, choices=Activity.choices, default=Activity.LIGHT
    )
    meals_per_day = models.CharField(
        max_length=12, choices=Meals.choices, default=Meals.THREE
    )
    restrictions = models.JSONField(
        default=list, blank=True,
        help_text="['halal','vegetarian','lactose_free','gluten_free','nut_allergy',...]",
    )
    obstacles = models.JSONField(
        default=list, blank=True,
        help_text="Nima to'xtatadi: ['discipline','habits','support','schedule'] — AI ohangi",
    )
    outcomes = models.JSONField(
        default=list, blank=True,
        help_text="Nimaga erishmoq: ['healthy_eating','energy_mood','motivation_discipline','body_look'] — AI fokusi",
    )
    target_overrides = models.JSONField(
        default=dict, blank=True,
        help_text="Foydalanuvchi qo'lda tahriri: {calories,carbs_g,protein_g,fat_g} — clamp'lanadi (doctor ustun)",
    )
    motivation = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        if self.user_id and not self.patient_profile_id:
            self.patient_profile_id = _patient_profile_id_for(self.user_id)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"DietProfile({self.user_id}, {self.goal})"
