from telegram import Update
from telegram.ext import ContextTypes

async def is_user_group_admin(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int) -> bool:
    chat_admins = await context.bot.get_chat_administrators(update.effective_chat.id)
    return any(admin.user.id == user_id for admin in chat_admins)

async def bot_has_permission(update: Update, context: ContextTypes.DEFAULT_TYPE, permission: str) -> bool:
    bot_member = await context.bot.get_chat_member(update.effective_chat.id, context.bot.id)
    return getattr(bot_member, permission, False)

def extract_target_user(update: Update):
    if update.effective_message.reply_to_message:
        return update.effective_message.reply_to_message.from_user
    return None
