"""Umumiy pagination — barcha list view'lar uchun (DEFAULT_PAGINATION_CLASS).

Default page_size=50 (mobil mijozlar shu bilan ishlaydi — backward-compatible).
`?page_size=` bilan client ko'proq so'rashi mumkin (max 500) — admin panel
statistika/agregatsiya sahifalari (revenue, balans, hisobotlar) butun
to'plamni bitta so'rovda olib to'g'ri jami hisoblashi uchun.
"""

from rest_framework.pagination import PageNumberPagination


class DefaultPagination(PageNumberPagination):
    page_size = 50
    page_size_query_param = "page_size"
    max_page_size = 500
