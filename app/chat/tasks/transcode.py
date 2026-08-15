from .common import *  # noqa: F401,F403 - umumiy importlar + konstantalar


# ---------------------------------------------------------------------------
# Voice message transcode (web webm/opus → m4a)
# ---------------------------------------------------------------------------


def _broadcast_message_updated(room_id, message_id, *, file_url, file_type, audio_status):
    """`message_updated` WS event'ini xona group'iga yuboradi (kontrakt: top-level
    fieldlar). Consumer `chat_message_updated` handler client'ga uzatadi.

    Channel layer o'chiq bo'lsa jim o'tadi — DB allaqachon yangilangan, client
    keyingi REST refresh'da to'g'ri holatni oladi."""
    try:
        async_to_sync(get_channel_layer().group_send)(
            f"chat_{room_id}",
            {
                "type": "chat.message_updated",
                "message_id": message_id,
                "room_id": room_id,
                "file_url": file_url,
                "file_type": file_type,
                "audio_status": audio_status,
            },
        )
    except Exception:
        logger.warning("message_updated broadcast o'tmadi (msg=%s)", message_id)


def _ffmpeg_webm_to_m4a(src_bytes: bytes) -> bytes:
    """webm/opus baytlarini m4a (AAC) baytlariga aylantiradi (ffmpeg subprocess).

    Limitlar (untrusted input DoS himoyasi):
      • `-t 300`              — max 5 daqiqa (uzun fayl cap)
      • `timeout=30`         — subprocess osilib qolmasin (buzuq fayl)
      • `-c:a aac -b:a 64k`  — ovoz uchun yetarli, kichik hajm
      • `-movflags +faststart` — m4a metadata boshida (web/stream uchun)

    tmpfile ishlatamiz (pipe emas) — m4a/mp4 muxer `+faststart` uchun seekable
    output talab qiladi, stdout pipe seek qila olmaydi.

    Raises:
        subprocess.CalledProcessError — ffmpeg non-zero exit (buzuq/qo'llab-quvvatlanmaydigan)
        subprocess.TimeoutExpired     — 30s'da tugamadi
    """
    tmpdir = tempfile.mkdtemp(prefix="voice_")
    src_path = os.path.join(tmpdir, "in.webm")
    dst_path = os.path.join(tmpdir, f"out_{uuid.uuid4().hex[:8]}.m4a")
    try:
        with open(src_path, "wb") as f:
            f.write(src_bytes)

        subprocess.run(
            [
                "ffmpeg",
                "-nostdin",
                "-hide_banner",
                "-loglevel", "error",
                "-y",
                "-t", str(TRANSCODE_MAX_DURATION_SEC),  # input'dan oldin — decode cap
                "-i", src_path,
                "-vn",                       # video oqimini tashlash (agar bo'lsa)
                "-c:a", "aac",
                "-b:a", "64k",
                "-movflags", "+faststart",
                dst_path,
            ],
            timeout=TRANSCODE_FFMPEG_TIMEOUT_SEC,
            check=True,
            capture_output=True,
        )

        with open(dst_path, "rb") as f:
            return f.read()
    finally:
        for p in (src_path, dst_path):
            try:
                os.remove(p)
            except OSError:
                pass
        try:
            os.rmdir(tmpdir)
        except OSError:
            pass


def _m4a_key_for(old_key: str) -> str:
    """Eski webm key'idan yangi m4a key — bir xil katalog (chat/{room}/...),
    kengaytma m4a, suffix `voice` (kontrakt: `...voice.m4a`).

    chat/{room_id}/ prefix'i saqlanadi — file_key xavfsizlik tekshiruvi (IDOR)
    yangi key uchun ham amal qiladi."""
    base = old_key.rsplit("/", 1)
    prefix = base[0] if len(base) == 2 else ""
    unique = uuid.uuid4().hex[:8]
    name = f"{unique}_voice.m4a"
    return f"{prefix}/{name}" if prefix else name


def _mark_failed(message, room_id, message_id):
    """audio_status=failed + message_updated(failed). Eski webm O'CHIRILMAYDI —
    client fallback sifatida original'ni baribir ijro qila oladi."""
    Message.objects.filter(id=message_id).update(audio_status="failed")
    _broadcast_message_updated(
        room_id,
        message_id,
        file_url=generate_download_url(message.file_key) if message.file_key else None,
        file_type=message.file_type,
        audio_status="failed",
    )


@shared_task(
    base=BaseTask,
    bind=True,
    name="chat.transcode_voice_message",
    queue="transcode",
)
def transcode_voice_message(self, message_id):
    """Web ovozli xabar (webm/opus) → m4a asinxron transcode.

    Oqim:
      1. Message'ni ol; idempotent — audio_status != "pending" bo'lsa skip.
      2. S3'dan webm yuklab ol (download_file_bytes).
      3. Hajm cap tekshiruvi (>20MB → permanent failed, retry yo'q).
      4. ffmpeg webm→m4a (-t 300, timeout 30) → m4a baytlar.
      5. Yangi `...voice.m4a` key'ga upload (chat/{room}/ prefix saqlanadi).
      6. message.file_key/file_type=audio/mp4/audio_status=ready saqla.
      7. `message_updated` WS broadcast (ready, yangi file_url).
      8. Eski webm key'ni 24h countdown bilan o'chirishga qo'y.

    Retry: transient xato (S3/ffmpeg crash) → BaseTask autoretry (max 3, backoff).
    Oxirgi urinish ham muvaffaqiyatsiz bo'lsa → audio_status=failed. Permanent
    validation xatosi (katta/buzuq fayl) → darhol failed, retry yo'q.
    """
    try:
        msg = Message.objects.select_related("room").get(id=message_id)
    except Message.DoesNotExist:
        return  # xabar o'chirilgan — hech narsa qilmaymiz

    # IDEMPOTENT: allaqachon ready (yoki failed, yoki audio emas) → skip.
    # Retry/duplicate delivery xavfsiz — ikki marta transcode bo'lmaydi.
    if msg.audio_status != "pending":
        logger.info(
            "transcode skip msg=%s (audio_status=%s)", message_id, msg.audio_status
        )
        return

    old_key = msg.file_key
    room_id = msg.room_id

    if not old_key:
        _mark_failed(msg, room_id, message_id)
        logger.warning("transcode msg=%s file_key bo'sh → failed", message_id)
        return

    # 1) S3'dan webm yuklab olish — transient xato bo'lsa raise (autoretry)
    try:
        src_bytes, _content_type = download_file_bytes(old_key)
    except Exception:
        # Oxirgi urinish bo'lsa failed deb belgilab to'xtaymiz, aks holda retry
        if self.request.retries >= self.max_retries:
            _mark_failed(msg, room_id, message_id)
            logger.exception(
                "transcode msg=%s S3 download oxirgi urinishda ham xato → failed",
                message_id,
            )
            return
        raise  # BaseTask autoretry

    # 2) Hajm cap — PERMANENT (buzuq/abuse webm worker'ni qiynamasin), retry yo'q
    if len(src_bytes) > TRANSCODE_MAX_INPUT_BYTES:
        _mark_failed(msg, room_id, message_id)
        logger.warning(
            "transcode msg=%s input %d bytes > cap → failed (retry yo'q)",
            message_id,
            len(src_bytes),
        )
        return

    # 3) ffmpeg webm→m4a
    try:
        m4a_bytes = _ffmpeg_webm_to_m4a(src_bytes)
    except subprocess.TimeoutExpired:
        # Buzuq fayl 30s'da tugamadi — PERMANENT, retry osilishni takrorlaydi
        _mark_failed(msg, room_id, message_id)
        logger.warning("transcode msg=%s ffmpeg timeout → failed (retry yo'q)", message_id)
        return
    except subprocess.CalledProcessError as exc:
        # ffmpeg non-zero (qo'llab-quvvatlanmaydigan/buzuq) — PERMANENT, retry yo'q
        _mark_failed(msg, room_id, message_id)
        logger.warning(
            "transcode msg=%s ffmpeg xato rc=%s → failed: %s",
            message_id,
            exc.returncode,
            (exc.stderr or b"")[:300],
        )
        return
    except FileNotFoundError:
        # ffmpeg binary yo'q (infra muammosi) — TRANSIENT (deploy tuzatishi mumkin)
        if self.request.retries >= self.max_retries:
            _mark_failed(msg, room_id, message_id)
            logger.error("transcode msg=%s ffmpeg topilmadi → failed", message_id)
            return
        raise

    if not m4a_bytes:
        _mark_failed(msg, room_id, message_id)
        logger.warning("transcode msg=%s bo'sh m4a → failed", message_id)
        return

    # 4) Yangi m4a key'ga upload — transient xato bo'lsa retry
    new_key = _m4a_key_for(old_key)
    try:
        upload_file_bytes(new_key, m4a_bytes, TRANSCODE_TARGET_MIME)
    except Exception:
        if self.request.retries >= self.max_retries:
            _mark_failed(msg, room_id, message_id)
            logger.exception("transcode msg=%s S3 upload oxirgi urinish → failed", message_id)
            return
        raise

    # 5) DB yangilash — file_key yangi m4a'ga ko'chadi, audio_status=ready.
    #    .update() — race-safe, atomic, signal'siz.
    Message.objects.filter(id=message_id).update(
        file_key=new_key,
        file_type=TRANSCODE_TARGET_MIME,
        file_size=len(m4a_bytes),
        audio_status="ready",
    )

    # 6) message_updated broadcast — yangi m4a file_url + ready
    _broadcast_message_updated(
        room_id,
        message_id,
        file_url=generate_download_url(new_key),
        file_type=TRANSCODE_TARGET_MIME,
        audio_status="ready",
    )

    # 7) Eski webm'ni 24h'dan keyin o'chirish — client'lar cache'dagi eski URL'ni
    #    hali ishlatayotgan bo'lishi mumkin (faststart almashuv davri). Idempotent:
    #    delete_file mavjud bo'lmasa False qaytaradi, retry-safe.
    try:
        delete_file_async.apply_async(
            args=[old_key], countdown=TRANSCODE_OLD_DELETE_COUNTDOWN
        )
    except Exception:
        logger.warning("transcode msg=%s eski webm delete schedule o'tmadi", message_id)

    logger.info("transcode msg=%s OK: %s → %s", message_id, old_key, new_key)


