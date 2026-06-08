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

BASE_URL      = "https://103-125-219-234.as-ty-cloud-xip.com/api"
GET_TOKEN_API = f"{BASE_URL}/auth/login"
GET_DATA_API  = f"{BASE_URL}/company_lid/user/2"
PATCH_API     = f"{BASE_URL}/company_lid"

bot = Bot(token=BOT_TOKEN)
dp  = Dispatcher(bot)

admin_groups: set[int] = set()

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
        data = res.json()
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
    now = time.time()
    remaining = _token_cache["expires_at"] - now

    if _token_cache["access_token"] and remaining > 0:
        hours = int(remaining // 3600)
        mins  = int((remaining % 3600) // 60)
        logger.info(f"♻️  Keshdan token ishlatildi (qoldi: {hours}s {mins}d)")
        return _token_cache["access_token"]

    logger.info("🔄 Token muddati tugagan, qayta login...")
    if _login():
        return _token_cache["access_token"]
    return None

async def refresh_token_daily():
    logger.info("🌅 Kunlik token yangilash...")
    _login()

def get_new_leads(token: str) -> list[dict]:
    try:
        headers = {"Authorization": f"Bearer {token}"}
        res = requests.get(GET_DATA_API, headers=headers, timeout=10)
        res.raise_for_status()
        data = res.json()
        all_leads = data.get("result", [])
        new_leads = [l for l in all_leads if l.get("status") == "NEW" and l.get("phone_number") is not None and l.get("full_name") is not None]
        logger.info(f"Jami: {len(all_leads)}, NEW: {len(new_leads)}")
        return new_leads
    except Exception as e:
        logger.error(f"Leadlarni olishda xato: {e}")
        return []

def mark_as_interested(token: str, lid_id: int) -> bool:
    try:
        headers = {"Authorization": f"Bearer {token}"}
        body = {"status": "INTERESTED", "message": ""}
        res = requests.patch(f"{PATCH_API}/{lid_id}", json=body, headers=headers, timeout=10)
        res.raise_for_status()
        logger.info(f"Lead #{lid_id} → INTERESTED")
        return True
    except Exception as e:
        logger.error(f"Status o'zgartirishda xato (#{lid_id}): {e}")
        return False

def format_lead(lead: dict) -> str:
    lid_id    = lead.get("id", "—")
    full_name = lead.get("full_name") or "—"
    phone     = lead.get("phone_number") or "—"
    username  = lead.get("username") or "—"
    return (
        f"🔔 <b>Yangi Lead!</b>\n\n"
        f"🆔 ID: <code>{lid_id}</code>\n"
        f"👤 Ism: <b>{full_name}</b>\n"
        f"📞 Telefon: <code>{phone}</code>\n"
        f"📸 Instagram: @{username}"
    )

async def send_leads_to_groups():
    if not admin_groups:
        return

    token = get_token()
    if not token:
        logger.error("Token olinmadi")
        return

    leads = get_new_leads(token)
    if not leads:
        return

    logger.info(f"{len(leads)} ta lead → {len(admin_groups)} ta guruh")

    for lead in leads:
        lid_id = lead.get("id")
        text   = format_lead(lead)

        for chat_id in list(admin_groups):
            try:
                await bot.send_message(chat_id, text, parse_mode="HTML")
                await asyncio.sleep(0.3)
            except Exception as e:
                logger.error(f"Guruhga yuborishda xato ({chat_id}): {e}")

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
        admin_groups.discard(chat_id)
        logger.info(f"Guruhdan chiqarildi: {chat_id}")

async def check_and_add_group(chat_id: int):
    try:
        bot_info = await bot.get_me()
        member   = await bot.get_chat_member(chat_id, bot_info.id)
        if member.status == "administrator":
            admin_groups.add(chat_id)
            logger.info(f"Admin guruh qo'shildi: {chat_id}")
    except Exception as e:
        logger.error(f"Guruhni tekshirishda xato ({chat_id}): {e}")

@dp.message_handler(commands=["start", "help"])
async def cmd_start(message: types.Message):
    await message.reply(
        "👋 <b>Leads Bot</b>\n\n"
        "Har <b>1 daqiqada</b> Instagram leadlarini olib,\n"
        "admin guruhlariga yuboraman.\n\n"
        "✅ Meni guruhga <b>admin</b> qilib qo'shing.",
        parse_mode="HTML"
    )

@dp.message_handler(commands=["status"])
async def cmd_status(message: types.Message):
    count       = len(admin_groups)
    groups_text = "\n".join(f"  • <code>{g}</code>" for g in admin_groups) or "  (yo'q)"

    remaining = _token_cache["expires_at"] - time.time()
    if remaining > 0:
        hours = int(remaining // 3600)
        mins  = int((remaining % 3600) // 60)
        token_info = f"✅ Faol (qoldi: {hours}s {mins}d)"
    else:
        token_info = "❌ Muddati tugagan (keyingi so'rovda yangilanadi)"

    await message.reply(
        f"📊 <b>Bot holati</b>\n\n"
        f"🔑 Token: {token_info}\n\n"
        f"👥 Admin guruhlar: <b>{count}</b>\n{groups_text}\n\n"
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
