from django.db import migrations

POSITIVE_TAGS = [
    ("explains_well", "Tushuntirib gapirdi", "Понятно объяснил", "💬"),
    ("attentive", "E'tiborli", "Внимательный", "👂"),
    ("on_time", "Vaqtni tejadi", "Сэкономил время", "⏱️"),
    ("recommend", "Tavsiya qilaman", "Рекомендую", "👍"),
    ("knowledgeable", "Bilimi kuchli", "Знающий специалист", "🎓"),
    ("kind", "Mehribon", "Добрый", "💚"),
    ("clean_clinic", "Klinika toza", "Чистая клиника", "✨"),
]

NEGATIVE_TAGS = [
    ("late", "Kech keldi", "Опоздал", "🕒"),
    ("rushed", "Shoshilib o'tkazdi", "Поспешил", "💨"),
    ("did_not_explain", "Tushuntirmadi", "Не объяснил", "🤐"),
    ("inattentive", "E'tibor bermadi", "Невнимателен", "😶"),
    ("not_recommend", "Tavsiya qilmayman", "Не рекомендую", "👎"),
]


def seed_tags(apps, schema_editor):
    ReviewTag = apps.get_model("feedbacks", "ReviewTag")

    for order, (slug, label_uz, label_ru, icon) in enumerate(POSITIVE_TAGS):
        ReviewTag.objects.update_or_create(
            slug=slug,
            defaults={
                "label_uz": label_uz,
                "label_ru": label_ru,
                "sentiment": "positive",
                "icon": icon,
                "order": order,
                "is_active": True,
            },
        )

    for order, (slug, label_uz, label_ru, icon) in enumerate(NEGATIVE_TAGS):
        ReviewTag.objects.update_or_create(
            slug=slug,
            defaults={
                "label_uz": label_uz,
                "label_ru": label_ru,
                "sentiment": "negative",
                "icon": icon,
                "order": order,
                "is_active": True,
            },
        )


def reverse_seed(apps, schema_editor):
    ReviewTag = apps.get_model("feedbacks", "ReviewTag")
    slugs = [s for s, *_ in POSITIVE_TAGS + NEGATIVE_TAGS]
    ReviewTag.objects.filter(slug__in=slugs).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("feedbacks", "0006_reviewtag_review_tags"),
    ]

    operations = [
        migrations.RunPython(seed_tags, reverse_seed),
    ]
