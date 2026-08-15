"""users views — UserViewSet mixinlarga bo'lingan (import yo'li o'zgarmas).

`from app.users.views import UserViewSet` ishlaydi — urls.py buzilmaydi.
"""

from .base import UserViewSet

# Top-level helperlar monolit views.py'da module-level edi — public import yuzasini
# saqlash uchun re-export (masalan app/users/deletion.py lazy `from app.users.views
# import _soft_delete_user` qiladi).
from .common import (  # noqa: F401
    _blacklist_user_tokens,
    _notify_admin_self_delete,
    _protect_root,
    _set_role,
    _soft_delete_user,
)

__all__ = ["UserViewSet"]
