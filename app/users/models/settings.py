from .common import *  # noqa: F401,F403
from .user import User


class UserSettings(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="settings")
    language = models.CharField(max_length=10, default="uz")
    theme = models.CharField(max_length=10, default="light")
    meeting_notification = models.BooleanField(default=True)
    discount_notification = models.BooleanField(default=True)
    health_packages_notification = models.BooleanField(default=True)
    dori_darmon_notification = models.BooleanField(default=True)
    news_notification = models.BooleanField(default=True)
