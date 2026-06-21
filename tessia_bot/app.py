from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from .config import TELEGRAM_TOKEN
from .state import load_data, mark_bot_started


def create_bot():
    return Bot(token=TELEGRAM_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))


def create_dispatcher(handlers_module):
    dp = Dispatcher()
    dp.message.register(handlers_module.on_text_message, F.text)
    dp.message.register(handlers_module.on_photo_message, F.photo)
    dp.message.register(handlers_module.on_animation_message, F.animation)
    dp.message.register(handlers_module.on_sticker_message, F.sticker)
    dp.message.register(handlers_module.on_document_message, F.document)
    dp.message.register(handlers_module.on_voice_message, F.voice)
    dp.message.register(handlers_module.on_audio_message, F.audio)
    dp.callback_query.register(handlers_module.on_panel_callback, F.data.startswith("panel:"))
    return dp


async def start_polling(handlers_module):
    load_data()
    bot = create_bot()
    await bot.delete_webhook(drop_pending_updates=True)
    mark_bot_started()
    dp = create_dispatcher(handlers_module)
    print("Tessia Bot Started - aiogram")
    await dp.start_polling(bot)
