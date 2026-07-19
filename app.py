import asyncio
import logging
import requests
import time
from aiogram.utils import executor
from aiogram import Bot, Dispatcher, types
from apscheduler.schedulers.asyncio import AsyncIOScheduler

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = "8893269835:AAFd_DKIa0_zl2NtAthXS9SmCbKw0tVnYxI"

AUTH_DATA = {
    "username": "akbarov504",
    "password": "12345678"
}

BASE_URL      = "https://74-113-233-27.as-ty-cloud-xip.com/api"
GET_TOKEN_API = f"{BASE_URL}/auth/login"
GET_DATA_API  = f"{BASE_URL}/company_lid/user/2"
PATCH_API     = f"{BASE_URL}/company_lid"

bot = Bot(token=BOT_TOKEN)
dp  = Dispatcher(bot)

admin_groups: dict[int, int | None] = {}

_token_cache = {
    "access_token":  None,
    "refresh_token": None,
    "expires_at":    0,
}
TOKEN_TTL = 23 * 60 * 60

def _login() -> bool:
    try:
        res = requests.post(GET_TOKEN_API, json=AUTH_DATA, timeout=10)
        res.raise_for_status()
        data   = res.json()
        result = data.get("result", {})
        access  = result.get("access_token")
        refresh = result.get("refresh_token")
        if not access:
            logger.error(f"access_token topilmadi: {data}")
            return False
        _token_cache["access_token"]  = access
        _token_cache["refresh_token"] = refresh
        _token_cache["expires_at"]    = time.time() + TOKEN_TTL
        logger.info("✅ Yangi token olindi (23 soatga saqlandi)")
        return True
    except Exception as e:
        logger.error(f"Login xato: {e}")
        return False

def get_token() -> str | None:
    remaining = _token_cache["expires_at"] - time.time()
    if _token_cache["access_token"] and remaining > 0:
        h, m = int(remaining // 3600), int((remaining % 3600) // 60)
        logger.info(f"♻️  Keshdan token (qoldi: {h}s {m}d)")
        return _token_cache["access_token"]
    logger.info("🔄 Token yangilanmoqda...")
    return _token_cache["access_token"] if _login() else None

async def refresh_token_daily():
    logger.info("🌅 Kunlik token yangilash...")
    _login()

def get_new_leads(token: str) -> list[dict]:
    try:
        headers = {"Authorization": f"Bearer {token}"}
        res = requests.get(GET_DATA_API, headers=headers, timeout=10)
        res.raise_for_status()
        all_leads = res.json().get("result", [])
        new_leads = [l for l in all_leads if l.get("status") == "NEW" and l.get("phone_number") is not None and l.get("full_name") is not None]
        logger.info(f"Jami: {len(all_leads)}, NEW: {len(new_leads)}")
        return new_leads
    except Exception as e:
        logger.error(f"Leadlarni olishda xato: {e}")
        return []

def mark_as_interested(token: str, lid_id: int) -> bool:
    try:
        headers = {"Authorization": f"Bearer {token}"}
        res = requests.patch(
            f"{PATCH_API}/{lid_id}",
            json={"status": "INTERESTED", "message": ""},
            headers=headers, timeout=10
        )
        res.raise_for_status()
        logger.info(f"Lead #{lid_id} → INTERESTED")
        return True
    except Exception as e:
        logger.error(f"Status xato (#{lid_id}): {e}")
        return False

def format_lead(lead: dict) -> str:
    return (
        f"🔔 <b>Yangi Lead!</b>\n\n"
        f"🆔 ID: <code>{lead.get('id', '—')}</code>\n"
        f"👤 Ism: <b>{lead.get('full_name') or '—'}</b>\n"
        f"📞 Telefon: <code>{lead.get('phone_number') or '—'}</code>\n"
        f"📸 Instagram: @{lead.get('username') or '—'}"
    )

async def send_leads_to_groups():
    if not admin_groups:
        return

    token = get_token()
    if not token:
        return

    leads = get_new_leads(token)
    if not leads:
        return

    for lead in leads:
        lid_id = lead.get("id")
        text   = format_lead(lead)

        for chat_id, thread_id in list(admin_groups.items()):
            try:
                await bot.send_message(
                    chat_id,
                    text,
                    parse_mode="HTML",
                    message_thread_id=thread_id
                )
                await asyncio.sleep(0.3)
            except Exception as e:
                logger.error(f"Yuborishda xato ({chat_id}, thread={thread_id}): {e}")

        if lid_id:
            mark_as_interested(token, lid_id)

@dp.message_handler(content_types=types.ContentType.NEW_CHAT_MEMBERS)
async def on_bot_join(message: types.Message):
    bot_info = await bot.get_me()
    for member in message.new_chat_members:
        if member.id == bot_info.id:
            await check_and_add_group(message.chat.id)

@dp.my_chat_member_handler()
async def on_chat_member_update(update: types.ChatMemberUpdated):
    chat_id    = update.chat.id
    new_status = update.new_chat_member.status
    if new_status in ("administrator", "member"):
        await check_and_add_group(chat_id)
    elif new_status in ("left", "kicked"):
        if chat_id in admin_groups:
            del admin_groups[chat_id]
            logger.info(f"Guruhdan chiqarildi: {chat_id}")

async def check_and_add_group(chat_id: int):
    try:
        bot_info = await bot.get_me()
        member   = await bot.get_chat_member(chat_id, bot_info.id)
        if member.status == "administrator":
            if chat_id not in admin_groups:
                admin_groups[chat_id] = None
            logger.info(f"Admin guruh qo'shildi: {chat_id}")
    except Exception as e:
        logger.error(f"Guruhni tekshirishda xato ({chat_id}): {e}")

@dp.message_handler(commands=["start", "help"])
async def cmd_start(message: types.Message):
    await message.reply(
        "👋 <b>Leads Bot</b>\n\n"
        "Har <b>1 daqiqada</b> NEW leadlarni tekshirib guruhga yuboraman.\n\n"
        "📌 Komandalar:\n"
        "/set_topic — shu topicni lead topici qilib belgilash\n"
        "/remove_topic — topicni o'chirib General ga qaytarish\n"
        "/status — bot holati\n"
        "/send_now — hozir yuborish",
        parse_mode="HTML"
    )

@dp.message_handler(commands=["set_topic"])
async def cmd_set_topic(message: types.Message):
    """Shu topic ichida yozilsa — shu topicni belgilaydi"""
    chat_id   = message.chat.id
    thread_id = message.message_thread_id  # Topic ichida bo'lsa ID keladi

    if message.chat.type not in ("group", "supergroup"):
        await message.reply("⚠️ Bu komanda faqat guruhda ishlaydi.")
        return

    if chat_id not in admin_groups:
        await check_and_add_group(chat_id)

    if chat_id not in admin_groups:
        await message.reply("❌ Men bu guruhda admin emasman. Avval admin qilib qo'ying.")
        return

    if not thread_id:
        await message.reply(
            "ℹ️ Hozir <b>General</b> da turibsiz.\n\n"
            "Leadlarni biror topicga yuborish uchun:\n"
            "1. Kerakli topicni oching\n"
            "2. O'sha yerda /set_topic yozing\n\n"
            "Yoki /remove_topic — General da qoldirasiz.",
            parse_mode="HTML"
        )
        return

    admin_groups[chat_id] = thread_id
    await message.reply(
        f"✅ <b>Topic belgilandi!</b>\n\n"
        f"Endi leadlar faqat shu topicga keladi.\n"
        f"🧵 Thread ID: <code>{thread_id}</code>\n\n"
        f"Bekor qilish: /remove_topic",
        parse_mode="HTML"
    )
    logger.info(f"Guruh {chat_id} → topic {thread_id} belgilandi")

@dp.message_handler(commands=["remove_topic"])
async def cmd_remove_topic(message: types.Message):
    """Topicni o'chirib General ga qaytaradi"""
    chat_id = message.chat.id

    if message.chat.type not in ("group", "supergroup"):
        await message.reply("⚠️ Bu komanda faqat guruhda ishlaydi.")
        return

    if chat_id not in admin_groups:
        await message.reply("❌ Bu guruh ro'yxatda yo'q.")
        return

    old_thread = admin_groups[chat_id]
    admin_groups[chat_id] = None

    if old_thread:
        await message.reply(
            f"✅ Topic (<code>{old_thread}</code>) o'chirildi.\n"
            f"Endi leadlar <b>General</b> ga keladi.",
            parse_mode="HTML"
        )
    else:
        await message.reply("ℹ️ Topic allaqachon o'rnatilmagan, General da ishlayapti.")

@dp.message_handler(commands=["status"])
async def cmd_status(message: types.Message):
    remaining = _token_cache["expires_at"] - time.time()
    if remaining > 0:
        h, m = int(remaining // 3600), int((remaining % 3600) // 60)
        token_info = f"✅ Faol (qoldi: {h}s {m}d)"
    else:
        token_info = "❌ Muddati tugagan"

    groups_text = ""
    for cid, tid in admin_groups.items():
        topic = f"🧵 topic: {tid}" if tid else "📢 General"
        groups_text += f"  • <code>{cid}</code> — {topic}\n"
    if not groups_text:
        groups_text = "  (yo'q)\n"

    await message.reply(
        f"📊 <b>Bot holati</b>\n\n"
        f"🔑 Token: {token_info}\n\n"
        f"👥 Admin guruhlar: <b>{len(admin_groups)}</b>\n{groups_text}\n"
        f"⏱ Har 1 daqiqada NEW leadlar tekshiriladi",
        parse_mode="HTML"
    )

@dp.message_handler(commands=["send_now"])
async def cmd_send_now(message: types.Message):
    await message.reply("⏳ Yuklanmoqda...")
    await send_leads_to_groups()
    await message.reply("✅ Bajarildi!")

async def on_startup(dp):
    logger.info("🔑 Boshlang'ich token olinmoqda...")
    _login()

    scheduler = AsyncIOScheduler()
    scheduler.add_job(send_leads_to_groups, "interval", minutes=1)
    scheduler.add_job(refresh_token_daily, "cron", hour=6, minute=0)
    scheduler.start()
    logger.info("✅ Bot ishga tushdi.")

if __name__ == "__main__":
    executor.start_polling(dp, on_startup=on_startup, skip_updates=True)
