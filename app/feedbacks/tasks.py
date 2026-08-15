import logging

from celery import shared_task

from app.feedbacks.models import Review
from app.notifications.models import Notification
from app.notifications.utils import notify_by_key
from core.tasks import BaseTask

logger = logging.getLogger(__name__)


@shared_task(base=BaseTask, bind=True, name="feedbacks.notify_doctor_new_review")
def notify_doctor_new_review(self, review_id: int):
    """Doctor'ga yangi review kelgani haqida (push + in-app notification)."""
    try:
        review = Review.objects.select_related("doctor__user", "patient").get(
            id=review_id
        )
    except Review.DoesNotExist:
        return

    doctor_user = review.doctor.user
    if not doctor_user:
        return

    star = "⭐" * review.rating
    snippet = (review.comment or "").strip()

    if snippet:
        key, params = "new_review_with_comment", {"stars": star, "snippet": snippet[:80]}
    else:
        key, params = "new_review", {"stars": star}

    notify_by_key(
        user=doctor_user,
        type=Notification.Type.NEW_REVIEW,
        key=key,
        params=params,
        data={
            "review_id": review_id,
            "doctor_id": review.doctor_id,
            "rating": review.rating,
        },
        app_scope="doctor",
    )
