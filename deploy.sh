#!/bin/bash
# Mediik Backend Deploy
#
# Bu script faqat Django backend (Docker) ni deploy qiladi.
# Admin panel va web landing alohida repolarga ajratildi:
#   - Admin: git@github.com:Mediik-uz/admin.git → /opt/admin
#   - Web:   git@github.com:Mediik-uz/web.git   → /opt/web
# Ularni yangilash uchun har papkada o'z deploy.sh skripti bor.

set -e

echo "=== Mediik Backend Deploy ==="

cd "$(dirname "$0")"

echo ">> Git pull..."
# Branch-aware: joriy branch'ni pull qiladi (main'da main, clinic branch'da clinic).
BRANCH=$(git branch --show-current)
git pull origin "$BRANCH"

echo ">> Docker build & restart..."
docker compose up -d --build

# Migratsiyalarni `web` konteynerining O'ZI ishga tushishida qiladi
# (docker-compose.yml: `migrate && daphne`) — daphne faqat migratsiyadan keyin
# ko'tariladi. Bu yerda YANA `migrate` chaqirish IKKI JARAYON POYGASINI
# yaratardi: konteyner ustun qo'shayotganda bu yerdagi migrate ham o'shani
# qo'shishga urinib "duplicate column" bilan yiqilardi.
# Endi faqat TEKSHIRAMIZ — qo'llanilmagani qolsa deploy shovqin bilan to'xtaydi.
echo ">> Migratsiyalar tekshirilmoqda..."
for i in $(seq 1 30); do
    if docker compose exec -T web python manage.py migrate --check --noinput > /dev/null 2>&1; then
        echo "   hammasi qo'llangan ✓"
        break
    fi
    if [ "$i" = "30" ]; then
        echo "   XATO: migratsiyalar qo'llanmadi. Konteyner logi:"
        docker compose logs --tail=40 web
        exit 1
    fi
    sleep 2
done

# Nginx reload (agar host nginx ishlatilsa)
if command -v nginx > /dev/null 2>&1; then
    echo ""
    echo ">> Reloading nginx..."
    sudo nginx -t && sudo systemctl reload nginx || echo "!! nginx reload skipped"
fi

# Docker cache tozalash — disk to'lib qolmasligi uchun (har deploy yangi image
# yaratadi, eski tag'siz qatlamlar to'planib boradi). 72 soatdan eski cache
# o'chiriladi — yaqin deploy'lar tezlatish uchun saqlanadi.
echo ""
echo ">> Docker cache tozalash..."
docker image prune -f 2>/dev/null | tail -1 || true
docker builder prune -f --filter "until=72h" 2>/dev/null | tail -1 || true

echo ""
echo ">> Done! Status:"
docker compose ps
