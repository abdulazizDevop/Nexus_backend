import logging
from datetime import datetime, timedelta, timezone as dt_timezone

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.db.models import Q
from django.utils import timezone

from app.chat.models import CallSession, ChatRoom, Message
from app.chat.tasks import (
    generate_chat_ai_reply,
    presence_offline_check,
    send_new_message_notification,
)
from app.chat.utils import (
    ONLINE_TTL,
    chat_peer_ids,
    enqueue_transcode_if_pending,
    initial_audio_status,
    set_last_seen,
    set_online,
    verify_chat_upload,
)
from services.storage import generate_download_url

logger = logging.getLogger(__name__)


def _avatar_url(key):
    """S3 key ni Bunny CDN signed URL ga aylantiradi."""
    return generate_download_url(key) if key else None


class ChatConsumer(AsyncJsonWebsocketConsumer):
    """Doctor-Patient chat WebSocket consumer."""

    async def connect(self):
        self.room_id = self.scope["url_route"]["kwargs"]["room_id"]
        self.room_group = f"chat_{self.room_id}"
        self.user = self.scope.get("user")
        self.jwt_scope = self.scope.get("jwt_scope")

        if not self.user or not self.user.is_authenticated:
            await self.close(code=4001)
            return

        is_participant = await self._is_participant()
        if not is_participant:
            await self.close(code=4003)
            return

        await self.channel_layer.group_add(self.room_group, self.channel_name)
        await self.accept()

        await self._set_online(True)

        logger.info("WS connected: user=%s room=%s", self.user.id, self.room_id)

    async def disconnect(self, code):
        if hasattr(self, "room_group"):
            await self.channel_layer.group_discard(self.room_group, self.channel_name)
        # Presence: online flag'ni set_online(False) bilan TOZALAMAYMIZ. Bitta ulanish
        # (chat WS) yopilishi butun user'ni offline qilmasin — app-level presence WS yoki
        # boshqa tab tirik bo'lishi mumkin. Flag'ni faqat TTL tushiradi (presence-safe).

    async def receive_json(self, content):
        msg_type = content.get("type")

        if msg_type == "text_message":
            await self._handle_text_message(content)
        elif msg_type == "file_message":
            await self._handle_file_message(content)
        elif msg_type == "typing":
            await self._handle_typing()
        elif msg_type == "mark_read":
            await self._handle_mark_read(content)
        elif msg_type == "end_call":
            await self._handle_end_call()
        elif msg_type == "heartbeat":
            await self._set_online(True)
        else:
            await self.send_json(
                {"type": "error", "message": f"Noma'lum type: {msg_type}"}
            )

    # --- Message handlers ---

    async def _handle_text_message(self, content):
        text = content.get("content", "").strip()
        if not text:
            await self.send_json({"type": "error", "message": "Matn bo'sh"})
            return

        # Connect paytida room aktiv edi, lekin admin yopib qo'ygan bo'lishi
        # mumkin (is_active=False). Har xabarda qaytadan tekshiramiz — yopilgan
        # chatga xabar yuborilmasin.
        if not await self._is_room_active():
            await self.send_json({"type": "error", "message": "Chat yopilgan"})
            return

        reply_to_id = content.get("reply_to")
        sent_at = self._parse_client_sent_at(content.get("client_sent_at"))
        try:
            message = await self._save_message(
                message_type="text",
                content=text,
                reply_to_id=reply_to_id,
                sent_at=sent_at,
            )
        except Exception:
            logger.exception("WS text message saqlashda xato room=%s", self.room_id)
            await self.send_json(
                {"type": "error", "message": "Xabar saqlanmadi"}
            )
            return

        await self.channel_layer.group_send(
            self.room_group,
            {"type": "chat.new_message", "message": message},
        )

        # AI gatekeeper: tarifsiz bemor xabariga AI javob beradi. Bunda doctor'ga
        # push YUBORILMAYDI (AI "egalik qiladi"). Cap tugagan bo'lsa — bemorga
        # `ai_limit_reached` signal (jim tashlamaymiz, mobil banner ko'rsatadi).
        outcome, doctor_id = await self._maybe_enqueue_ai_reply(message["id"])
        if outcome == "doctor":
            await self._notify_offline(message["id"])
        elif outcome == "limit":
            await self.send_json(
                {"type": "ai_limit_reached", "doctor_id": doctor_id}
            )

    @database_sync_to_async
    def _maybe_enqueue_ai_reply(self, message_id):
        """Tarifsiz bemor xabarini AI gatekeeper bo'yicha ko'rib chiqadi.

        Returns (outcome, doctor_id):
          - ("doctor", None)   → AI-rejim emas, odatdagi doctor push yuboriladi.
          - ("queued", id)     → AI javob navbatga qo'yildi (doctor push yo'q).
          - ("limit", id)      → cap tugadi, AI yo'q (doctor push yo'q, bemorga signal).
        """
        from django.core.cache import cache

        from app.chat.ai.gate import should_ai_handle, under_cap

        try:
            room = ChatRoom.objects.select_related(
                "patient__user", "doctor__user"
            ).get(id=self.room_id)
        except ChatRoom.DoesNotExist:
            return ("doctor", None)
        allowed, doctor = should_ai_handle(room, self.user, self.jwt_scope)
        if not allowed:
            return ("doctor", None)
        if not under_cap(self.user, doctor):
            return ("limit", doctor.id)
        # Burst-lock: tez ketma-ket xabarlarda bir nechta task spawn bo'lmasin.
        if cache.add(f"chatai:lock:{self.user.id}:{doctor.id}", 1, timeout=8):
            generate_chat_ai_reply.delay(self.room_id, message_id)
        return ("queued", doctor.id)

    @database_sync_to_async
    def _verify_uploaded_file(self, file_key):
        """S3 HeadObject — real MIME/size tekshiruvi (spoofing/malware oldini olish).

        Xavfsizlik-kritik mantiq app/chat/utils.py:verify_chat_upload da — support
        reply view ham aynan shuni chaqiradi (drift oldini olish).
        """
        return verify_chat_upload(file_key)

    async def _handle_file_message(self, content):
        file_key = content.get("file_key", "")
        if not file_key:
            await self.send_json({"type": "error", "message": "file_key kerak"})
            return

        # XAVFSIZLIK: file_key AYNAN shu xonaga tegishli bo'lishi shart.
        # upload-url har doim "chat/{room_id}/..." key beradi; client boshqa
        # xona yoki boshqa resurs (avatars/, certificates/...) key'ini yubora
        # olmasligi kerak — aks holda cross-resource fayl oshkor bo'ladi (IDOR).
        if not file_key.startswith(f"chat/{self.room_id}/"):
            await self.send_json({"type": "error", "message": "Noto'g'ri file_key"})
            return

        if not await self._is_room_active():
            await self.send_json({"type": "error", "message": "Chat yopilgan"})
            return

        # XAVFSIZLIK: S3'dagi HAQIQIY obyektni HeadObject bilan tekshiramiz.
        # Client "image/jpeg" deb URL olib, S3'ga ixtiyoriy bayt (masalan .exe)
        # PUT qilishi mumkin edi — real MIME/size'ni qaytadan tekshirib, mos
        # bo'lmasa faylni o'chiramiz. file_type/file_size/message_type ham
        # client'dan emas, real obyektdan olinadi.
        verified = await self._verify_uploaded_file(file_key)
        if not verified["ok"]:
            await self.send_json({"type": "error", "message": verified["error"]})
            return

        sent_at = self._parse_client_sent_at(content.get("client_sent_at"))
        try:
            message = await self._save_message(
                message_type=verified["message_type"],
                content=content.get("content", ""),
                file_key=file_key,
                file_name=content.get("file_name", ""),
                file_size=verified["size"],
                file_type=verified["mime"],
                sent_at=sent_at,
            )
        except Exception:
            logger.exception("WS file message saqlashda xato room=%s", self.room_id)
            await self.send_json(
                {"type": "error", "message": "Xabar saqlanmadi"}
            )
            return

        await self.channel_layer.group_send(
            self.room_group,
            {"type": "chat.new_message", "message": message},
        )

        await self._notify_offline(message["id"])

    async def _handle_typing(self):
        await self.channel_layer.group_send(
            self.room_group,
            {"type": "chat.typing", "user_id": self.user.id},
        )

    async def _handle_mark_read(self, content):
        message_id = content.get("message_id")
        if not message_id:
            return
        # Kontrakt: mijozlar (mobil/web) message_id'ni string yoki int yuborishi
        # mumkin — int'ga normallashtiramiz, shunda read_receipt HAR DOIM int bo'lib
        # ketadi (web `typeof number` tekshiruvi string'ni rad etib ✓✓ qo'ymasdi).
        try:
            message_id = int(message_id)
        except (TypeError, ValueError):
            return

        read_at = await self._mark_message_read(message_id)
        if read_at:
            await self.channel_layer.group_send(
                self.room_group,
                {
                    "type": "chat.read_receipt",
                    "message_id": message_id,
                    "user_id": self.user.id,
                    "read_at": read_at,
                },
            )

    # --- Group message handlers (broadcast) ---

    async def chat_new_message(self, event):
        message = event["message"]
        # file_key bo'lsa Bunny CDN URL generatsiya qilish
        if message.get("file_key"):
            message["file_url"] = generate_download_url(message["file_key"])
        await self.send_json({"type": "new_message", "message": message})

    async def chat_message_updated(self, event):
        """Ovozli xabar transcode tugaganda (webm→m4a) yangilangan fieldlar.

        Celery transcode task group_send qiladi. Kontrakt (mobil jamoa bilan) —
        top-level fieldlar, `message` ob'ekti emas. Client message_id bo'yicha
        topib file_url/file_type/audio_status'ni almashtiradi.
        """
        await self.send_json(
            {
                "type": "message_updated",
                "message_id": event["message_id"],
                "room_id": event["room_id"],
                "file_url": event.get("file_url"),
                "file_type": event.get("file_type"),
                "audio_status": event.get("audio_status"),
            }
        )

    async def chat_typing(self, event):
        if event["user_id"] != self.user.id:
            await self.send_json({"type": "typing", "user_id": event["user_id"]})

    async def chat_read_receipt(self, event):
        if event["user_id"] != self.user.id:
            await self.send_json(
                {
                    "type": "read_receipt",
                    "message_id": event["message_id"],
                    "user_id": event["user_id"],
                    "read_at": event["read_at"],
                }
            )

    # --- DB operations ---

    @database_sync_to_async
    def _is_participant(self):
        # Admin barcha support chatlarga kira oladi
        if self.user.role == "admin":
            if ChatRoom.objects.filter(
                id=self.room_id,
                room_type=ChatRoom.RoomType.SUPPORT,
                is_active=True,
            ).exists():
                return True

        return ChatRoom.objects.filter(
            id=self.room_id,
            participants=self.user,
            is_active=True,
        ).exists()

    @database_sync_to_async
    def _is_room_active(self) -> bool:
        """Har xabar oldidan room.is_active'ni tekshiradi.

        Connect paytida active edi, lekin admin chatni yopib qo'ygan bo'lishi
        mumkin (yoki cron task avtomatik yopgan). Bu tekshiruvsiz yopilgan
        chatga xabar oqib turaverardi.
        """
        return ChatRoom.objects.filter(id=self.room_id, is_active=True).exists()

    def _parse_client_sent_at(self, raw):
        """Mobile yuborgan epoch ms timestamp'ni datetime'ga aylantiradi.

        Audio/file upload 2-bosqichli (presigned PUT + WS event) — parallel
        upload tugashi tartibsiz bo'lgani sababli `Message.created_at` ni
        client send order'ga moslash uchun shu helper ishlatiladi.

        Xavfsizlik chegaralari:
          • None / yaroqsiz qiymat   → server now() (fallback, eski client)
          • Kelajakdagi > 5 daqiqa   → server now() (telefon vaqti noto'g'ri)
          • O'tmishdagi > 24 soat    → server now() (delayed delivery abuse)
        """
        if raw is None:
            return timezone.now()
        try:
            ms = int(raw)
        except (TypeError, ValueError):
            return timezone.now()
        try:
            sent = datetime.fromtimestamp(ms / 1000, tz=dt_timezone.utc)
        except (OverflowError, OSError, ValueError):
            return timezone.now()
        now = timezone.now()
        if sent > now + timedelta(minutes=5):
            return now
        if sent < now - timedelta(hours=24):
            return now
        return sent

    @database_sync_to_async
    def _save_message(
        self,
        message_type,
        content="",
        file_key="",
        file_name="",
        file_size=None,
        file_type="",
        reply_to_id=None,
        sent_at=None,
    ):
        room = ChatRoom.objects.get(id=self.room_id)

        # XAVFSIZLIK/BUG: reply_to_id faqat AYNI shu xonadagi mavjud (o'chirilmagan)
        # xabarga ishora qilishi shart. Yaroqsiz ID → FK IntegrityError (consumer
        # task crash); boshqa xona xabari → cross-room reply reference. Mos
        # kelmasa reply'ni e'tiborsiz qoldiramiz.
        if reply_to_id and not Message.objects.filter(
            id=reply_to_id, room_id=self.room_id, is_deleted=False
        ).exists():
            reply_to_id = None

        # Ovozli xabar: kelishilgan skip-logic bo'yicha boshlang'ich holat.
        # webm/opus/ogg → "pending" (transcode), mos format → "ready", aks → None.
        audio_status = initial_audio_status(message_type, file_type, file_name)

        create_kwargs = dict(
            room=room,
            sender=self.user,
            sender_scope=self.jwt_scope,
            message_type=message_type,
            content=content,
            file_key=file_key,
            file_name=file_name,
            file_size=file_size,
            file_type=file_type,
            audio_status=audio_status,
            reply_to_id=reply_to_id,
        )
        if sent_at is not None:
            create_kwargs["created_at"] = sent_at

        msg = Message.objects.create(**create_kwargs)

        room.updated_at = timezone.now()
        room.save(update_fields=["updated_at"])

        # ASYNC-SAFETY: `.delay()` (Celery broker I/O) shu sync-helper ICHIDA
        # chaqiriladi — `_save_message` `database_sync_to_async` bilan o'ralgan,
        # ya'ni alohida thread'da sinxron bajariladi. Async event loop'da
        # to'g'ridan-to'g'ri chaqirilmaydi (CLAUDE.md qoidasi).
        enqueue_transcode_if_pending(msg.id, audio_status)

        # Frontend Patient.id va DoctorProfile.id'ni bilishi kerak —
        # User.id ambiguous bo'lishi mumkin (bir user ham bemor, ham doctor).
        patient_profile = getattr(self.user, "patient_profile", None)
        doctor_profile = getattr(self.user, "doctor_profile", None)

        return {
            "id": msg.id,
            "sender": {
                "id": self.user.id,
                "patient_profile_id": patient_profile.id if patient_profile else None,
                "doctor_profile_id": doctor_profile.id if doctor_profile else None,
                "full_name": self.user.full_name,
                "avatar": _avatar_url(self.user.avatar),
                "role": self.user.role,
                "admin_type": getattr(self.user, "admin_type", None),
            },
            "sender_name": self.user.full_name,
            "sender_role": self.user.role,
            "sender_scope": msg.sender_scope,
            "sender_admin_type": getattr(self.user, "admin_type", None),
            "message_type": msg.message_type,
            "content": msg.content,
            "file_key": msg.file_key,
            "file_name": msg.file_name,
            "file_size": msg.file_size,
            "file_type": msg.file_type,
            "audio_status": msg.audio_status,
            "reply_to": msg.reply_to_id,
            "is_read": False,
            "is_ai": msg.is_ai,
            "created_at": msg.created_at.isoformat(),
        }

    @database_sync_to_async
    def _mark_message_read(self, message_id):
        """Boshqaning xabarini o'qilgan deb belgilab read_at qaytaradi (broadcast uchun).

        REST `mark-read` (bulk is_read=True) WS `mark_read` bilan poyga qiladi:
        REST oldin yetib xabarni o'qilgan qilsa, bu yerda filter(is_read=False)
        hech narsa topmas va sender hech qachon read_receipt (✓✓) olmasdi. Shuning
        uchun xabar allaqachon o'qilgan bo'lsa ham mavjud read_at'ni qaytaramiz —
        broadcast tartibga bog'liq bo'lmasdan har doim ketsin. Faqat boshqaning
        (exclude sender) mavjud xabari uchun; o'z xabari/yo'q bo'lsa None.
        """
        now = timezone.now()
        msg = (
            Message.objects.filter(id=message_id, room_id=self.room_id)
            .exclude(sender=self.user)
            .only("id", "is_read", "read_at")
            .first()
        )
        if msg is None:
            return None
        if not msg.is_read:
            Message.objects.filter(id=msg.id).update(is_read=True, read_at=now)
            return now.isoformat()
        return (msg.read_at or now).isoformat()

    async def _set_online(self, online):
        set_online(self.user.id, online)

    async def _notify_offline(self, message_id):
        """Offline user ga Telegram notification (Celery task)."""
        try:
            send_new_message_notification.delay(message_id)
        except Exception:
            pass  # Redis/Celery o'chiq bo'lsa skip

    async def _handle_end_call(self):
        """WebSocket orqali call tugatish."""
        @database_sync_to_async
        def _find_active_call():
            return (
                CallSession.objects.filter(
                    room_id=self.room_id,
                    status__in=[CallSession.Status.RINGING, CallSession.Status.ACTIVE],
                )
                .filter(Q(caller=self.user) | Q(callee=self.user))
                .first()
            )

        session = await _find_active_call()

        if not session:
            await self.send_json(
                {"type": "error", "message": "Aktiv qo'ng'iroq topilmadi"}
            )
            return

        now = timezone.now()
        if session.status == CallSession.Status.ACTIVE and session.started_at:
            session.status = CallSession.Status.COMPLETED
            session.duration = int((now - session.started_at).total_seconds())
        else:
            session.status = CallSession.Status.CANCELLED

        session.ended_at = now
        await database_sync_to_async(
            lambda: session.save(update_fields=["status", "ended_at", "duration"])
        )()

        content = session.system_message_finished()

        msg = await self._save_message(message_type="system", content=content)

        await self.channel_layer.group_send(
            self.room_group,
            {
                "type": "call.event",
                "event": "call_ended",
                "call_session_id": session.id,
                "duration": session.duration,
            },
        )
        await self.channel_layer.group_send(
            self.room_group,
            {"type": "chat.new_message", "message": msg},
        )

    # --- Call event broadcast handler ---

    async def call_event(self, event):
        """call.event → client'ga yuborish (incoming_call, call_accepted, va h.k.)"""
        await self.send_json(
            {
                "type": event["event"],
                "call_session_id": event.get("call_session_id"),
                "call_type": event.get("call_type"),
                "caller_id": event.get("caller_id"),
                "caller_name": event.get("caller_name"),
                "duration": event.get("duration"),
                "reason": event.get("reason"),
            }
        )


# Tarmoq uzilishi (clean background EMAS)'дан keyin offline check'ni TTL tugagach
# chaqiramiz — qayta ulanmasa offline broadcast. ONLINE_TTL + bufer (flap oldini olish).
PRESENCE_OFFLINE_GRACE = ONLINE_TTL + 5


class PresenceConsumer(AsyncJsonWebsocketConsumer):
    """App-level presence WebSocket (`/ws/presence/`).

    ChatConsumer'dan FARQLI — bitta xonaga emas, app foreground'da turganда butun
    app uchun doim ochiq. Online'ni user-darajasida belgilaydi va o'zgarishni
    chat-peer'larga (umumiy xonasi bor user'lar) broadcast qiladi.

    Lifecycle:
      connect             → set_online(True) + last_seen=now + peer'larga "online"
      heartbeat (~30s)    → TTL yangilanadi (broadcast YO'Q — peer allaqachon biladi)
      background / drop   → flag DARHOL tozalanmaydi (multi-tab/multi-ulanish xavfsiz):
                            Celery offline-check TTL tugagach, BOSHQA ulanish (boshqa tab
                            yoki chat WS) flag'ni yangilamagan bo'lsa offline broadcast
                            qiladi. Hech bir disconnect set_online(False) chaqirmaydi —
                            offline faqat TTL + check orqali (tarmoq blip'da flap yo'q).

    Xavfsizlik: broadcast faqat chat-peer'larga (online-status bilan bir xil filtr).
    Online user-darajasida (`chat:online:{uid}`) — bitta nomer 2 app bo'lsa ham bitta.
    """

    async def connect(self):
        self.user = self.scope.get("user")
        self.jwt_scope = self.scope.get("jwt_scope")

        if not self.user or not self.user.is_authenticated:
            await self.close(code=4001)
            return

        self.presence_group = f"presence_{self.user.id}"
        self._went_background = False

        await self.channel_layer.group_add(self.presence_group, self.channel_name)
        await self.accept()

        self._refresh_online()
        await self._broadcast(online=True, last_seen=None)

        logger.info("Presence WS connected: user=%s", self.user.id)

    async def disconnect(self, code):
        if not getattr(self, "user", None) or not self.user.is_authenticated:
            return
        if hasattr(self, "presence_group"):
            await self.channel_layer.group_discard(
                self.presence_group, self.channel_name
            )
        if getattr(self, "_went_background", False):
            return  # `background` xabari allaqachon offline qildi
        # Tarmoq uzilishi (background signalisiz): DARHOL offline qilmaymiz. TTL
        # tugashini kutamiz — Celery check qayta ulanmasa offline broadcast qiladi.
        await self._schedule_offline_check()

    async def receive_json(self, content):
        msg_type = content.get("type")
        if msg_type == "heartbeat":
            self._refresh_online()
        elif msg_type == "background":
            # Clean background — socket yopilishidan oldin. Flag'ni DARHOL tozalamaymiz
            # (boshqa tab/ulanish tirik bo'lishi mumkin — bitta ulanish butun user'ni
            # offline qilmasin). Offline-check TTL tugagach, qayta ulanmasa/boshqa ulanish
            # bo'lmasa offline broadcast qiladi. (Socket ochiq qolsa ham check ishlaydi.)
            self._went_background = True
            await self._schedule_offline_check()
        # boshqa type'lar e'tiborsiz — presence kanali faqat shu ikkitasini biladi

    # --- helpers ---

    def _refresh_online(self):
        """Online flag + last_seen TTL yangilash (cache — sync, ORM emas)."""
        set_online(self.user.id, True)
        set_last_seen(self.user.id, timezone.now().isoformat())

    async def _broadcast(self, online, last_seen):
        """Presence o'zgarishini chat-peer'larga uzatadi (umumiy xonasi borlarga)."""
        peer_ids = await self._peer_ids()
        for pid in peer_ids:
            await self.channel_layer.group_send(
                f"presence_{pid}",
                {
                    "type": "presence.event",
                    "user_id": self.user.id,
                    "online": online,
                    "last_seen": last_seen,
                },
            )

    @database_sync_to_async
    def _peer_ids(self):
        return chat_peer_ids(self.user.id)

    @database_sync_to_async
    def _schedule_offline_check(self):
        try:
            presence_offline_check.apply_async(
                args=[self.user.id], countdown=PRESENCE_OFFLINE_GRACE
            )
        except Exception:
            pass  # broker o'chiq bo'lsa skip — TTL baribir flag'ni tushiradi

    async def presence_event(self, event):
        """Boshqa user presence o'zgarganda — shu client'ga uzatish."""
        if event.get("user_id") == self.user.id:
            return
        await self.send_json(
            {
                "type": "presence",
                "user_id": event["user_id"],
                "online": event["online"],
                "last_seen": event.get("last_seen"),
            }
        )
