from rest_framework.settings import api_settings
from rest_framework.views import exception_handler


def custom_exception_handler(exc, context):
    """Custom exception handler to format errors consistently"""
    response = exception_handler(exc, context)

    if response is not None:
        if isinstance(response.data, dict) and "detail" not in response.data:
            errors = []
            non_field_key = api_settings.NON_FIELD_ERRORS_KEY
            for field, messages in response.data.items():
                # Object-level (non-field) xatolarda texnik kalit nomini
                # foydalanuvchiga ko'rsatmaymiz — faqat xabarning o'zi.
                prefix = "" if field == non_field_key else f"{field}: "
                if isinstance(messages, list):
                    for msg in messages:
                        errors.append(f"{prefix}{msg}")
                else:
                    errors.append(f"{prefix}{messages}")
            response.data = {"detail": errors[0] if len(errors) == 1 else errors}

        # 401/403 uchun mashina-o'qiladigan `code` qo'shamiz (additive, backward-
        # compatible — mavjud `detail` saqlanadi). Frontend `doctor_not_verified`
        # kabi holatni matnga qarab emas, kod orqali ajratsin.
        if (
            isinstance(response.data, dict)
            and "code" not in response.data
            and response.status_code in (401, 403)
        ):
            code = getattr(exc, "default_code", None)
            if isinstance(code, str):
                response.data["code"] = code

    return response
