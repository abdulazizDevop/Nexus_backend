from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .atmos_views import (
    AtmosCardViewSet,
    AtmosConfirmView,
    AtmosPayView,
    AtmosWebhookView,
)
from .views import (
    AdminGrantProView,
    AdminRevokeProView,
    AdminUserProHistoryView,
    AtmosAslDepositHistoryView,
    AtmosAslDepositView,
    AtmosAslTransactionsView,
    ClickWebhookView,
    DoctorBalanceAdminViewSet,
    DoctorBalanceView,
    DoctorPayoutCardViewSet,
    DoctorPayoutRequestViewSet,
    DoctorSalesStatsView,
    DoctorSalesView,
    DoctorTariffAdminViewSet,
    DoctorTariffPublicViewSet,
    DoctorTariffViewSet,
    DoctorTopupView,
    DoctorWalletOperationsView,
    DoctorWalletSummaryView,
    MyProSubscriptionView,
    MyPurchasesView,
    OfflinePaymentViewSet,
    PaymentAdminViewSet,
    PayoutRequestAdminViewSet,
    PaymeWebhookView,
    ProFeatureFlagAdminViewSet,
    ProPlanAdminViewSet,
    ProPlansView,
    ProSubscribeView,
    SystemSettingAdminViewSet,
)

router = DefaultRouter()
# Patient
router.register("doctor-tariffs", DoctorTariffPublicViewSet, basename="doctor-tariff-public")
# Doctor
router.register("doctor/tariffs", DoctorTariffViewSet, basename="doctor-tariff")
router.register("doctor/cards", DoctorPayoutCardViewSet, basename="doctor-card")
# Offline to'lov (bemor yaratadi, doctor tasdiqlaydi)
router.register("offline", OfflinePaymentViewSet, basename="offline-payment")
router.register(
    "doctor/payouts", DoctorPayoutRequestViewSet, basename="doctor-payout"
)
# Admin
router.register("admin/pro-plans", ProPlanAdminViewSet, basename="admin-pro-plan")
router.register("admin/pro-features", ProFeatureFlagAdminViewSet, basename="admin-pro-feature")
router.register("admin/settings", SystemSettingAdminViewSet, basename="admin-setting")
router.register("admin/doctor-tariffs", DoctorTariffAdminViewSet, basename="admin-doctor-tariff")
router.register("admin/payments", PaymentAdminViewSet, basename="admin-payment")
router.register("admin/doctor-balances", DoctorBalanceAdminViewSet, basename="admin-doctor-balance")
router.register(
    "admin/payouts", PayoutRequestAdminViewSet, basename="admin-payout"
)
# Atmos (Patient)
router.register("atmos/cards", AtmosCardViewSet, basename="atmos-card")

urlpatterns = [
    path("", include(router.urls)),
    # Pro (Patient)
    path("pro/plans/", ProPlansView.as_view(), name="pro-plans"),
    path("pro/me/", MyProSubscriptionView.as_view(), name="pro-me"),
    path("pro/subscribe/", ProSubscribeView.as_view(), name="pro-subscribe"),
    # Patient purchases
    path("my-purchases/", MyPurchasesView.as_view(), name="my-purchases"),
    # Doctor balance & sales
    path("doctor/balance/", DoctorBalanceView.as_view(), name="doctor-balance"),
    # Doctor balansni to'ldirish (provayder checkout)
    path("topup/", DoctorTopupView.as_view(), name="doctor-topup"),
    path("doctor/sales/", DoctorSalesView.as_view(), name="doctor-sales"),
    path(
        "doctor/sales-stats/",
        DoctorSalesStatsView.as_view(),
        name="doctor-sales-stats",
    ),
    # Doctor wallet (Hamyon)
    path(
        "doctor/wallet/summary/",
        DoctorWalletSummaryView.as_view(),
        name="doctor-wallet-summary",
    ),
    path(
        "doctor/wallet/operations/",
        DoctorWalletOperationsView.as_view(),
        name="doctor-wallet-operations",
    ),
    # Admin — Pro obuna manual boshqaruv
    path(
        "admin/users/<int:user_id>/grant-pro/",
        AdminGrantProView.as_view(),
        name="admin-grant-pro",
    ),
    path(
        "admin/users/<int:user_id>/revoke-pro/",
        AdminRevokeProView.as_view(),
        name="admin-revoke-pro",
    ),
    path(
        "admin/users/<int:user_id>/pro-history/",
        AdminUserProHistoryView.as_view(),
        name="admin-pro-history",
    ),
    # Atmos to'lov (Patient) — saqlangan karta orqali
    path("atmos/pay/", AtmosPayView.as_view(), name="atmos-pay"),
    path("atmos/pay/confirm/", AtmosConfirmView.as_view(), name="atmos-pay-confirm"),
    # Webhook (paytechuz handle qiladi — signature/auth tekshiruvi ichida)
    path("webhook/payme/", PaymeWebhookView.as_view(), name="payme-webhook"),
    path("webhook/click/", ClickWebhookView.as_view(), name="click-webhook"),
    # Atmos webhook (alohida — paytechuz emas, direct API)
    path("webhook/atmos/", AtmosWebhookView.as_view(), name="atmos-webhook"),
    # ATMOS ASL (payout — doctor balansidan kartaga) admin
    path(
        "admin/atmos-asl/deposit/",
        AtmosAslDepositView.as_view(),
        name="atmos-asl-deposit",
    ),
    path(
        "admin/atmos-asl/transactions/",
        AtmosAslTransactionsView.as_view(),
        name="atmos-asl-transactions",
    ),
    path(
        "admin/atmos-asl/deposit-history/",
        AtmosAslDepositHistoryView.as_view(),
        name="atmos-asl-deposit-history",
    ),
]
