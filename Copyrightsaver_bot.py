import asyncio
import json
import logging
import os
from telegram import Update, InputMediaPhoto, InputMediaVideo, InputMediaDocument, Sticker, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes, Application
from telegram.error import Forbidden

# Disable logging for `httpx`
logging.getLogger("httpx").setLevel(logging.WARNING)

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Constants
OWNER_ID = '7574316340'  # Replace with the actual owner ID
DATA_FILE = "data.json"
DEFAULT_AUTO_DELETE_TIME = 30 * 60  # Default auto delete time in seconds (30 minutes)

# Data Structures
authorized_users = set()
authorized_user_ids = set()
started_users = set()
group_ids = set()
global_authorized_users = set()
group_authorized_users = {}
group_settings = {}

# Load data from JSON file
def load_data():
    try:
        with open(DATA_FILE, "r") as file:
            content = file.read().strip()
            if not content:
                logger.info(f"{DATA_FILE} is empty. Creating default data.")
                return {}
            return json.loads(content)
    except (json.JSONDecodeError, FileNotFoundError) as e:
        logger.error(f"Error loading data: {e}")
        return {}

# Save data to JSON file
def save_data():
    data = {
        "started_users": list(started_users),
        "group_ids": list(group_ids),
        "authorized_users": list(authorized_users),
        "authorized_user_ids": list(authorized_user_ids),
        "global_authorized_users": list(global_authorized_users),
        "group_authorized_users": {k: list(v) for k, v in group_authorized_users.items()},
        "group_settings": group_settings
    }
    with open(DATA_FILE, "w") as file:
        json.dump(data, file, indent=4)

# Authorize a user
def authorize_user(user_id):
    if user_id not in authorized_user_ids:
        authorized_user_ids.add(user_id)
        authorized_users.append(user_id)
        logger.info(f"User {user_id} authorized!")
    else:
        logger.info(f"User {user_id} is already authorized.")

# Initialize data
data = load_data()
started_users = set(data.get("started_users", []))
group_ids = set(data.get("group_ids", []))
authorized_users = data.get("authorized_users", [])
authorized_user_ids = set(data.get("authorized_user_ids", []))
global_authorized_users = set(data.get("global_authorized_users", []))
group_authorized_users = {k: set(v) for k, v in data.get("group_authorized_users", {}).items()}
group_settings = data.get("group_settings", {})

save_data()  # Save data after initializing

# Set timer for auto-delete
async def set_timer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    chat_id = update.message.chat.id

    # Check if the user is an admin or owner
    if not await is_admin_or_owner(user_id, chat_id, context.bot):
        await update.message.reply_text("Only group admins or the owner can set the auto-delete timer.")
        return

    # Ensure a timer value is provided
    if len(context.args) != 1:
        await update.message.reply_text("Usage: /settimer <time_in_minutes> (e.g., /settimer 30)")
        return
    try:
        timer_minutes = int(context.args[0])
        if timer_minutes <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("Please provide a valid positive integer for the time in minutes.")
        return

    # Set the timer for the group
    group_settings[chat_id] = {"delete_timer": timer_minutes * 60, "auto_delete": True}
    save_data()

    await update.message.reply_text(f"Auto-delete timer set to {timer_minutes} minutes for this group.")

# Handle auto-delete logic
async def handle_auto_delete(update, delete_timer):
    print(f"Delete timer set to: {delete_timer} seconds")  # Debugging line
    await asyncio.sleep(delete_timer)
    await update.message.delete()


CMD_ON = 'on'
CMD_OFF = 'off'
async def toggle_auto_delete(update, context):
    chat_id = str(update.message.chat.id)

    group_config = group_settings.get(
        chat_id,
        {"delete_timer": DEFAULT_AUTO_DELETE_TIME, "auto_delete": True}
    )

    if context.args:
        option = context.args[0].lower()

        if option == CMD_ON:
            group_config["auto_delete"] = True
        elif option == CMD_OFF:
            group_config["auto_delete"] = False
        else:
            await update.message.reply_text("Usage: /autodlt <on|off>")
            return

        group_settings[chat_id] = group_config
        save_data()
        auto_delete_status = "enabled" if group_config["auto_delete"] else "disabled"
        await update.message.reply_text(f"Auto-delete is now {auto_delete_status} for this group.")
    else:
        await update.message.reply_text("Usage: /autodlt <on|off>")


def load_auth_data():
    """Loads JSON data from a file, returns an empty dictionary if the file doesn't exist or an error occurs."""
    try:
        if not os.path.exists('data.json'):
            print("Data file does not exist. Initializing with empty data.")
            return {}
        with open('data.json', 'r') as file:
            data = json.load(file)
            print("Data loaded successfully:", data)
            return data
    except json.JSONDecodeError as e:
        print(f"Error decoding JSON file: {e}. Returning empty data.")
        return {}
    except Exception as e:
        print(f"Unexpected error loading JSON file: {e}")
        return {}

def save_auth_data(updated_data):
    """Merges updated data with existing data and saves to a file."""
    try:
        existing_data = load_auth_data()  # Load existing data
        merged_data = {**existing_data, **updated_data}  # Merge existing and updated data

        with open('data.json', 'w') as file:
            json.dump(merged_data, file, indent=4)  # Save the merged JSON data
        print("Data saved successfully. Current data:", merged_data)
    except Exception as e:
        print(f"Error saving JSON file: {e}")
def merge_dicts(d1, d2):
    """Recursively merges two dictionaries."""
    for k, v in d2.items():
        if isinstance(v, dict) and k in d1 and isinstance(d1[k], dict):
            d1[k] = merge_dicts(d1[k], v)
        else:
            d1[k] = v
    return d1

async def is_admin_or_owner(user_id, chat_id, bot):
    if user_id == int(OWNER_ID):
        return True
    chat_admins = await bot.get_chat_administrators(chat_id)
    return any(admin.user.id == user_id for admin in chat_admins)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        chat_type = update.message.chat.type

        if chat_type == 'private':
            keyboard = [
                [InlineKeyboardButton("📜 Commands", url='https://t.me/copyrightprotection/4')],
                [InlineKeyboardButton("📞 Contact", url='https://t.me/Imthanos_bot')],
                [InlineKeyboardButton("🔄 Update", url='https://t.me/copyrightprotection')],
                [InlineKeyboardButton("➕ Add Me to Your Group", url='https://t.me/copyrightprotection1_bot?startgroup=true')],
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await update.message.reply_text(
                'Hey! I can Save Your Group From Unwanted Copyright Issues 🚀',
                reply_markup=reply_markup
            )

        else:
            keyboard = [
                [InlineKeyboardButton("❓ Help", url='https://t.me/copyrightprotection1_bot')],
                [InlineKeyboardButton("➕ Add Me to Your Group", url='https://t.me/copyrightprotection1_bot?startgroup=true')],
                [InlineKeyboardButton("📞 Contact", url='https://t.me/Imthanos_bot')],
                [InlineKeyboardButton("🔄 Update", url='https://t.me/copyrightprotection')],
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await update.message.reply_text(
                'Hey! I can Save Your Group From Unwanted Copyright Issues 🚀',
                reply_markup=reply_markup
            )

    except Exception as e:
        logger.error(f"Error in /start command: {e}")

async def authorize_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    chat_id = update.message.chat.id

    # Check if the command is a reply to another user's message
    if update.message.reply_to_message:
        new_user_id = update.message.reply_to_message.from_user.id
    else:
        # Ensure a proper argument is provided
        if len(context.args) < 1:
            await update.message.reply_text("Usage: /auth <user_id> or reply to a user's message with /auth")
            return
        try:
            new_user_id = int(context.args[0])
        except ValueError:
            await update.message.reply_text("Invalid user ID. Please provide a valid numeric user ID.")
            return

    # Load authentication data
    auth_data = load_auth_data() or {'global_authorized_users': [], 'group_authorized_users': {}}

    if user_id == int(OWNER_ID):
        # Owner is authorizing; add to global only
        if new_user_id not in auth_data['global_authorized_users']:
            auth_data['global_authorized_users'].append(new_user_id)
            save_auth_data(auth_data)
            await update.message.reply_text(f"User {new_user_id} has been authorized by owner.")
        else:
            await update.message.reply_text(f"User {new_user_id} is already globally authorized.")
    else:
        # Check if the user is an admin or owner for group-specific authorization
        if not await is_admin_or_owner(user_id, chat_id, context.bot):
            await update.message.reply_text("Only group admins or the owner can authorize users.")
            return

        # Handle group authorization for non-owner
        group_authorized_users = auth_data['group_authorized_users']
        if str(chat_id) not in group_authorized_users:
            group_authorized_users[str(chat_id)] = []
        if new_user_id not in group_authorized_users[str(chat_id)]:
            group_authorized_users[str(chat_id)].append(new_user_id)
            auth_data['group_authorized_users'] = group_authorized_users
            save_auth_data(auth_data)

            await update.message.reply_text(f"User {new_user_id} has been authorized in this group.")
        else:
            await update.message.reply_text(f"User {new_user_id} is already authorized in this group.")

async def unauthorize_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    chat_id = update.message.chat.id

    # Load authorization data
    auth_data = load_auth_data() or {'global_authorized_users': [], 'group_authorized_users': {}}
    group_admins = auth_data['group_authorized_users'].get(str(chat_id), [])

    # Check if the user is the bot owner or a group admin
    if user_id != int(OWNER_ID) and user_id not in group_admins:
        await update.message.reply_text("Only the owner or group admins can unauthorize users.")
        return

    # Check if the command is used with a user_id
    if context.args:
        try:
            target_user_id = int(context.args[0])  # Extract user_id from the command argument
        except ValueError:
            await update.message.reply_text("Invalid user ID. Please provide a valid numeric user ID.")
            return
    elif update.message.reply_to_message:
        # User is replying to a message
        target_user_id = update.message.reply_to_message.from_user.id
    else:
        await update.message.reply_text("Usage: Please provide a user ID with /unauth <user_id> or reply to a user's message.")
        return

    if user_id == int(OWNER_ID):
        # Remove from global authorized list
        if target_user_id in auth_data['global_authorized_users']:
            auth_data['global_authorized_users'].remove(target_user_id)
            await update.message.reply_text(f"User {target_user_id} has been unauthorized by Owner.")
        else:
            await update.message.reply_text(f"User {target_user_id} was not authorized by Owner.")

    # Remove from group authorized list
    if target_user_id in group_admins:
        group_admins.remove(target_user_id)
        await update.message.reply_text(f"User {target_user_id} has been unauthorized from group.")

    # Save the updated authorization data
    save_auth_data(auth_data)


# Example save_auth_data and load_auth_data functions
def save_auth_data(data):
    with open('auth_data.json', 'w') as f:
        json.dump(data, f)

def load_auth_data():
    try:
        with open('auth_data.json', 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        return None


async def list_groups(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id != int(OWNER_ID):
        await update.message.reply_text("Only the bot owner can use this command.")
        return

    valid_groups = []

    # Loop through all group IDs
    for group_id in group_ids:
        try:
            # Try to get the group chat information
            chat = await context.bot.get_chat(group_id)

            # Count the group only if its title is not None or empty
            if chat.title:
                valid_groups.append(chat.title)
        except Exception as e:
            # Skip any group where fetching details failed (no valid group)
            continue

    if valid_groups:
        group_names = "\n".join(valid_groups)
        await update.message.reply_text(f"The bot is added to the following valid groups:\n{group_names}\n\nTotal number of valid groups: {len(valid_groups)}")
    else:
        await update.message.reply_text("The bot is not added to any valid groups.")



async def count_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id != int(OWNER_ID):
        await update.message.reply_text("Only the bot owner can use this command.")
        return

    total_users = len(started_users)
    await update.message.reply_text(f"Total number of users who started the bot: {total_users}")


async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id != int(OWNER_ID):
        await update.message.reply_text("Only the bot owner can use this command.")
        return

    if not update.message.reply_to_message:
        await update.message.reply_text("Please reply to a message to broadcast it.")
        return

    recipients = list(started_users | group_ids)
    success_count = 0
    failure_count = 0

    try:
        # Check the type of the message to be broadcasted
        if update.message.reply_to_message.sticker:
            media = update.message.reply_to_message.sticker.file_id
            for recipient in recipients:
                try:
                    await context.bot.send_sticker(chat_id=recipient, sticker=media)
                    success_count += 1
                except Exception as e:
                    print(f"Failed to send to {recipient}: {e}")
                    failure_count += 1
        elif update.message.reply_to_message.photo:
            media = update.message.reply_to_message.photo[-1].file_id
            for recipient in recipients:
                try:
                    await context.bot.send_photo(chat_id=recipient, photo=media)
                    success_count += 1
                except Exception as e:
                    print(f"Failed to send to {recipient}: {e}")
                    failure_count += 1
        elif update.message.reply_to_message.video:
            media = update.message.reply_to_message.video.file_id
            for recipient in recipients:
                try:
                    await context.bot.send_video(chat_id=recipient, video=media)
                    success_count += 1
                except Exception as e:
                    print(f"Failed to send to {recipient}: {e}")
                    failure_count += 1
        elif update.message.reply_to_message.document:
            media = update.message.reply_to_message.document.file_id
            for recipient in recipients:
                try:
                    await context.bot.send_document(chat_id=recipient, document=media)
                    success_count += 1
                except Exception as e:
                    print(f"Failed to send to {recipient}: {e}")
                    failure_count += 1
        elif update.message.reply_to_message.text:
            media = update.message.reply_to_message.text
            for recipient in recipients:
                try:
                    await context.bot.send_message(chat_id=recipient, text=media)
                    success_count += 1
                except Exception as e:
                    print(f"Failed to send to {recipient}: {e}")
                    failure_count += 1
        else:
            await update.message.reply_text("Unsupported media type for broadcasting.")
            return

        # Send broadcast completion summary
        await update.message.reply_text(
            f"Broadcast completed.\n\n"
            f"✅ Successfully sent to: {success_count}\n"
            f"❌ Failed to send to: {failure_count}"
        )

    except Exception as e:
        await update.message.reply_text(f"An error occurred during broadcast: {e}")

async def handle_edited_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.edited_message.from_user
    chat_id = update.edited_message.chat.id
    user_id = user.id

    # Load authentication data
    auth_data = load_auth_data() or {'global_authorized_users': [], 'group_authorized_users': {}}

    # Check if the user is globally authorized
    if user_id in auth_data['global_authorized_users']:
        return

    # Check if the user is authorized in the specific group
    if str(chat_id) in auth_data['group_authorized_users'] and user_id in auth_data['group_authorized_users'][str(chat_id)]:
        return

    try:
        username = user.mention_html()
        announcement = f" 𝘙𝘰𝘴𝘦𝘴 𝘢𝘳𝘦 𝘳𝘦𝘥, 𝘷𝘪𝘰𝘭𝘦𝘵𝘴 𝘢𝘳𝘦 𝘣𝘭𝘶𝘦, {username} 𝘦𝘥𝘪𝘵𝘦𝘥 𝘢 𝘮𝘦𝘴𝘴𝘢𝘨𝘦, 𝘯𝘰𝘸 𝘪𝘵'𝘴 𝘨𝘰𝘯𝘦 𝘛𝘰𝘰!😮‍💨"

        # Send announcement about the edited message
        await context.bot.send_message(chat_id=chat_id, text=announcement, parse_mode="HTML")

        # Delete the edited message
        await update.edited_message.delete()
    except Exception as e:
        print(f"Failed to delete edited message: {e}")


import json
import asyncio
import json
import asyncio
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

# Function to load the auth data from the JSON file
def load_auth_data():
    try:
        with open('data.json', 'r') as file:
            return json.load(file)  # Load the JSON data
    except Exception as e:
        print(f"Error loading JSON file: {e}")
        return {}

# Function to save auth data to JSON file (if you want to dynamically update the file)
def save_auth_data(data):
    try:
        with open('data.json', 'w') as file:
            json.dump(data, file, indent=4)  # Save the JSON data
    except Exception as e:
        print(f"Error saving JSON file: {e}")
# Function to handle message deletion
async def delete_message(context, chat_id, message_id, delete_timer):
    try:
        await asyncio.sleep(delete_timer)  # Wait before deleting
        await context.bot.delete_message(chat_id=chat_id, message_id=message_id)  # Attempt to delete the message

    except Exception as e:
        print(f"")

# Function to handle new messages
async def handle_new_message(update, context):
    try:
        # Check if update.message exists and is valid
        if update.message is None:
            print("Error: No message found in the update.")
            return  # Exit early if there's no message

        # Reload auth data dynamically every time a message is handled
        auth_data = load_auth_data()

        # Ensure chat and message are available
        chat_id = update.message.chat.id if update.message.chat else None
        message_id = update.message.message_id if update.message.message_id else None
        user_id = update.message.from_user.id if update.message.from_user else None

        # If any necessary attribute is missing, log and return
        if not chat_id or not message_id or not user_id:
            print("Error: Missing chat, message, or user data.")
            return

        # Fetch the group configuration for the chat
        group_config = auth_data.get('group_settings', {}).get(str(chat_id), {})

        # Check if the user is globally authorized
        if user_id in auth_data["global_authorized_users"]:
            return

        # Check if the user is authorized in the specific group
        elif str(chat_id) in auth_data["group_authorized_users"] and user_id in auth_data["group_authorized_users"].get(str(chat_id), []):
            return

        # If auto-delete is enabled for the group, proceed with deletion
        if group_config.get("auto_delete", False):
            # Check the message type and the text auto-delete setting
            is_media_message = bool(update.message.photo or update.message.video or update.message.document or update.message.audio)
            text_auto_delete = group_config.get("text_auto_delete", True)

            # Determine if the message should be deleted based on its type
            if text_auto_delete or is_media_message:
                delete_timer = group_config.get("delete_timer", 10)  # Default to 10 seconds if no timer is set
                asyncio.create_task(delete_message(context, chat_id, message_id, delete_timer))

    except Exception as e:
        print(f"Error in handle_new_message: {e}")
async def set_timer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message is None:
        print("No message found in update")  # Debugging line
        return

    user_id = update.message.from_user.id
    chat_id = update.message.chat.id

    # Check if the user is an admin or owner
    if not await is_admin_or_owner(user_id, chat_id, context.bot):
        await update.message.reply_text("Only group admins or the owner can change the delete timer.")
        return

    # Ensure a proper argument is provided
    if len(context.args) != 1 or not context.args[0].isdigit():
        await update.message.reply_text("Usage: /settimer <time_in_minutes>")
        return

    # Get the timer value from the command argument and convert from minutes to seconds
    delete_time_minutes = int(context.args[0])
    delete_time_seconds = delete_time_minutes * 60  # Convert to seconds

    # Load the current group settings
    auth_data = load_auth_data()
    group_settings = auth_data.get('group_settings', {})

    if str(chat_id) not in group_settings:
        group_settings[str(chat_id)] = {}

    # Update the delete timer for the group
    group_settings[str(chat_id)]['delete_timer'] = delete_time_seconds

    # Save the updated settings
    auth_data['group_settings'] = group_settings
    save_auth_data(auth_data)

    await update.message.reply_text(f"Delete timer has been set to {delete_time_minutes} minute(s) for this group.")



async def new_chat_member(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat = update.effective_chat
    new_members = update.message.new_chat_members

    if chat.type in ['group', 'supergroup']:
        for member in new_members:
            if member.id == context.bot.id:
                try:
                    await context.bot.send_message(
                        chat_id=chat.id,
                        text="Hey! Thanks for adding me to your group. Click - /start to enable my functions 🙃"
                    )
                except Forbidden:
                    print(f"Cannot send message to chat {chat.id}. The bot might have been removed or lacks permissions.")
                break  # No need to check other members once the bot is found

async def toggle_text_auto_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    chat_id = update.message.chat.id

    # Check if the user is an admin or owner
    if not await is_admin_or_owner(user_id, chat_id, context.bot):
        await update.message.reply_text("Only group admins or the owner can change the text auto-delete setting.")
        return

    # Ensure a proper argument is provided
    if len(context.args) != 1 or context.args[0].lower() not in ["on", "off"]:
        await update.message.reply_text("Usage: /textautodlt <on|off>")
        return

    # Update the text auto-delete setting for the group
    text_auto_delete = context.args[0].lower() == "on"

    # Load the authentication data from the JSON file
    auth_data = load_auth_data()
    group_settings = auth_data.get('group_settings', {})

    # Ensure the group settings exist for this chat
    if str(chat_id) not in group_settings:
        group_settings[str(chat_id)] = {}

    # Set the default value to False (off) if it's not already set
    current_setting = group_settings[str(chat_id)].get('text_auto_delete', False)  # Default is False (off)

    # Update the text auto-delete setting based on the command
    group_settings[str(chat_id)]['text_auto_delete'] = text_auto_delete

    # Save the updated data without resetting other settings
    auth_data['group_settings'] = group_settings
    save_auth_data(auth_data)

    status = "enabled" if text_auto_delete else "disabled"
    await update.message.reply_text(f"Text auto-delete has been {status} for this group.")
async def show_group_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    chat_id = update.message.chat.id

    # Load data from the JSON file
    data = load_data()  # Assuming load_data loads the settings from 'data.json'
    group_settings = data.get("group_settings", {})

    # Ensure the group settings exist for the current chat
    if str(chat_id) in group_settings:
        settings = group_settings[str(chat_id)]
        delete_timer_seconds = settings.get('delete_timer', DEFAULT_AUTO_DELETE_TIME)
        delete_timer_minutes = delete_timer_seconds / 60  # Convert back to minutes for display

        await update.message.reply_text(
            f"Group Settings:\nDelete timer: {delete_timer_minutes} minute(s)\nAuto-delete: {'enabled' if settings.get('auto_delete', True) else 'disabled'}"
        )
    else:
        await update.message.reply_text("No settings found for this group.")


from telegram import Update, ChatMember
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

# Helper function to load settings from data.json
import json

def load_data():
    with open("data.json", "r") as f:
        return json.load(f)

async def show_group_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat.id
    auth_data = load_auth_data()
    group_settings = auth_data.get('group_settings', {})

    if str(chat_id) not in group_settings:
        await update.message.reply_text("No settings found for this group.")
        return

    group_setting = group_settings[str(chat_id)]

    # Get the delete time and auto delete settings
    delete_time = group_setting.get('delete_timer', 'Not set')
    auto_delete = group_setting.get('auto_delete', 'Not set')

    # Default behavior: if 'text_auto_delete' is not set, assume it is enabled (on)
    text_auto_delete = group_setting.get('text_auto_delete', True)  # Default to True (enabled)

    # Format the status as "on" or "off"
    text_auto_delete_status = "enabled" if text_auto_delete else "disabled"

    # Prepare the message
    settings_message = (
        f"Group Settings:\n"
        f"Delete time: {delete_time} min\n"
        f"Auto delete: {'on' if auto_delete else 'off'}\n"
        f"Text auto delete: {text_auto_delete_status}"
    )
    await update.message.reply_text(settings_message)

def main():
    application = ApplicationBuilder().token("7738387262:AAFlJILd8J2BupXtBGBhSOYpKr3Uf5diP-s").build()

    # Adding CommandHandlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("auth", authorize_user))
    application.add_handler(CommandHandler("unauth", unauthorize_user))
    application.add_handler(CommandHandler("listgroup", list_groups))
    application.add_handler(CommandHandler("countuser", count_users))
    application.add_handler(CommandHandler("broadcast", broadcast))
    application.add_handler(CommandHandler("settimer", set_timer))
    application.add_handler(CommandHandler("autodlt", toggle_auto_delete))
    application.add_handler(CommandHandler("textautodlt", toggle_text_auto_delete))

    # Add the /showsetting command handler
    showsetting_handler = CommandHandler("showsetting", show_group_settings)
    application.add_handler(showsetting_handler)

    # Add other handlers like new chat members, new messages, etc.
    application.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, new_chat_member))
    application.add_handler(MessageHandler(filters.ALL & ~filters.UpdateType.EDITED_MESSAGE, handle_new_message))
    application.add_handler(MessageHandler(filters.UpdateType.EDITED_MESSAGE, handle_edited_message))
    application.add_handler(MessageHandler(filters.ALL & ~filters.UpdateType.EDITED_MESSAGE, delete_message))
    application.add_handler(MessageHandler(filters.ALL, handle_auto_delete))

    # Start the bot
    application.run_polling()

if __name__ == "__main__":
    main()


