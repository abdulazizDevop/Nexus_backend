"""payments view'lari — modullarga bo'lingan (import yo'llari o'zgarmaydi).

`from app.payments.views import X` ishlashda davom etadi. urls.py (31 view),
tasks.py va atmos_views.py (`_complete_payment`, `_verify_webhook_amount`)
importlari buzilmaydi.
"""

from .admin import (
    AdminGrantProView,
    AdminRevokeProView,
    AdminUserProHistoryView,
    AtmosAslDepositHistoryView,
    AtmosAslDepositView,
    AtmosAslTransactionsView,
    DoctorBalanceAdminViewSet,
    DoctorTariffAdminViewSet,
    PaymentAdminViewSet,
    PayoutRequestAdminViewSet,
    ProFeatureFlagAdminViewSet,
    ProPlanAdminViewSet,
    SystemSettingAdminViewSet,
)
from .offline import DoctorTopupView, OfflinePaymentViewSet
from .pro import MyProSubscriptionView, ProPlansView, ProSubscribeView
from .sales import DoctorSalesStatsView, DoctorSalesView
from .tariff import (
    DoctorBalanceView,
    DoctorTariffPublicViewSet,
    DoctorTariffViewSet,
    MyPurchasesView,
)
from .wallet import (
    DoctorPayoutCardViewSet,
    DoctorPayoutRequestViewSet,
    DoctorWalletOperationsView,
    DoctorWalletSummaryView,
)
from .webhook import (
    ClickWebhookView,
    PaymeWebhookView,
    _complete_payment,
    _verify_webhook_amount,
)

__all__ = [
    "ProPlansView", "MyProSubscriptionView", "ProSubscribeView",
    "DoctorTariffPublicViewSet", "MyPurchasesView", "DoctorTariffViewSet", "DoctorBalanceView",
    "OfflinePaymentViewSet", "DoctorTopupView",
    "DoctorPayoutCardViewSet", "DoctorWalletSummaryView", "DoctorWalletOperationsView",
    "DoctorPayoutRequestViewSet",
    "DoctorSalesView", "DoctorSalesStatsView",
    "ProPlanAdminViewSet", "ProFeatureFlagAdminViewSet", "SystemSettingAdminViewSet",
    "DoctorTariffAdminViewSet", "PaymentAdminViewSet", "DoctorBalanceAdminViewSet",
    "PayoutRequestAdminViewSet", "AtmosAslDepositView", "AtmosAslTransactionsView",
    "AtmosAslDepositHistoryView", "AdminGrantProView", "AdminRevokeProView", "AdminUserProHistoryView",
    "PaymeWebhookView", "ClickWebhookView",
    "_complete_payment", "_verify_webhook_amount",
]
