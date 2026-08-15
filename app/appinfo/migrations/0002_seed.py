from django.db import migrations

SEED = {
    "patient": {
        "ios_url": "https://apps.apple.com/uz/app/mediik/id6762194727",
        "android_url": "https://play.google.com/store/apps/details?id=com.mediik.patient",
    },
    "doctor": {
        "ios_url": "https://apps.apple.com/uz/app/mediik-doctor/id6762198734",
        "android_url": "https://play.google.com/store/apps/details?id=com.mediik.doctor",
    },
}


def seed(apps, schema_editor):
    MobileAppInfo = apps.get_model("appinfo", "MobileAppInfo")
    for scope, defaults in SEED.items():
        MobileAppInfo.objects.get_or_create(app_scope=scope, defaults=defaults)


def unseed(apps, schema_editor):
    MobileAppInfo = apps.get_model("appinfo", "MobileAppInfo")
    MobileAppInfo.objects.filter(app_scope__in=SEED).delete()


class Migration(migrations.Migration):
    dependencies = [("appinfo", "0001_initial")]
    operations = [migrations.RunPython(seed, unseed)]
