from .common import *  # noqa: F401,F403 - umumiy importlar + services + konstantalar
from .common import _limit_exceeded_response


@extend_schema(tags=["Diet AI - Patient"])
class DietConversationViewSet(viewsets.ModelViewSet):
    """Bemor — suhbatlar CRUD va xabar yuborish."""

    permission_classes = [IsPatient]
    queryset = DietConversation.objects.none()
    http_method_names = ["get", "post", "delete", "head", "options"]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return DietConversation.objects.none()
        return DietConversation.objects.filter(user=self.request.user).prefetch_related(
            "messages"
        )

    _serializer_by_action = {
        "create": DietConversationCreateSerializer,
        "retrieve": DietConversationDetailSerializer,
        "send_message": SendMessageSerializer,
    }

    def get_serializer_class(self):
        if not hasattr(self.request, "user") or not self.request.user.is_authenticated:
            return DietConversationListSerializer
        return self._serializer_by_action.get(self.action, DietConversationListSerializer)

    @extend_schema(summary="Mening suhbatlarim")
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @extend_schema(summary="Yangi suhbat yaratish")
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        conversation = serializer.save(user=request.user)
        return Response(
            DietConversationDetailSerializer(conversation).data,
            status=status.HTTP_201_CREATED,
        )

    @extend_schema(summary="Suhbat batafsil + xabarlar tarixi")
    def retrieve(self, request, *args, **kwargs):
        return super().retrieve(request, *args, **kwargs)

    @extend_schema(summary="Suhbatni arxivlash (o'chirish o'rniga)")
    def destroy(self, request, *args, **kwargs):
        conv = self.get_object()
        conv.is_archived = True
        conv.save(update_fields=["is_archived"])
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(
        request=SendMessageSerializer,
        responses=DietMessageSerializer,
        summary="Suhbatga xabar yuborish (text)",
        description=(
            "AI javobi to'liq qaytariladi (non-streaming). "
            "Streaming uchun WebSocket ishlatiladi (kelajakda)."
        ),
    )
    @action(detail=True, methods=["post"], url_path="messages")
    def send_message(self, request, pk=None):
        conversation = self.get_object()

        # 1. Limit
        limit_info = services.check_daily_limit(request.user)
        if not limit_info["allowed"]:
            return _limit_exceeded_response(limit_info, include_info=True)

        # 2. Conversation message limit
        if services.should_suggest_new_chat(conversation):
            return Response(
                {
                    "detail": (
                        "Bu suhbat juda uzun bo'lib qoldi. "
                        "Tokenlarni tejash uchun yangi suhbat oching."
                    ),
                    "suggest_new_chat": True,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # 3. Validate input
        serializer = SendMessageSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user_text = serializer.validated_data["content"].strip()
        if not user_text:
            return Response(
                {"detail": "Xabar bo'sh bo'lmasligi kerak."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # 4. Xavfsizlik tekshiruvi (xabar saqlashdan oldin)
        dangerous, _reason = is_dangerous(user_text)
        if dangerous:
            DietMessage.objects.create(
                conversation=conversation,
                role=DietMessage.Role.USER,
                content=user_text,
                is_blocked=True,
            )
            safety_text = get_safety_response(conversation.language)
            assistant_msg = DietMessage.objects.create(
                conversation=conversation,
                role=DietMessage.Role.ASSISTANT,
                content=safety_text,
                is_blocked=True,
            )
            conversation.save(update_fields=["updated_at"])
            return Response(DietMessageSerializer(assistant_msg).data)

        # 5. AI uchun history (yangi xabar saqlashdan OLDIN, history toza bo'lishi uchun)
        user_context = services.build_user_context(request.user)
        system_prompt = build_system_prompt(conversation.language, user_context)
        history = services.build_history_for_ai(conversation)

        # 6. AI'ga so'rov (saqlashdan oldin — xato bo'lsa user xabar qolib ketmaydi)
        result = generate_text(
            prompt=user_text,
            system_instruction=system_prompt,
            history=history,
        )

        if "error" in result:
            return Response(
                {"detail": result["error"]},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        # 7. Endi user + assistant xabarlarini birga saqlash (atomic)
        with transaction.atomic():
            DietMessage.objects.create(
                conversation=conversation,
                role=DietMessage.Role.USER,
                content=user_text,
            )
            assistant_msg = DietMessage.objects.create(
                conversation=conversation,
                role=DietMessage.Role.ASSISTANT,
                content=result["text"],
                tokens_input=result["tokens_input"],
                tokens_output=result["tokens_output"],
            )

            if not conversation.title:
                conversation.title = services.auto_generate_title(user_text)
                conversation.save(update_fields=["title", "updated_at"])
            else:
                conversation.save(update_fields=["updated_at"])

        # 8. Limit oshirish (transactiondan tashqarida — alohida update)
        services.increment_usage(
            request.user,
            tokens_input=result["tokens_input"],
            tokens_output=result["tokens_output"],
        )

        return Response(DietMessageSerializer(assistant_msg).data)


