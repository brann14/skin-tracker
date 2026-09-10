# bot.py - main bot file that will load all the cogs and run the bot (can be found on https://github.com/brann14/bot-guide/blob/main/main.py)

import os
import discord
from discord.ext import commands
from dotenv import load_dotenv
from pathlib import Path

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN not found in environment variables")

# Configure intents required for basic command handling
intents = discord.Intents.default()
intents.message_content = True

# Initialize the bot instance
bot = commands.Bot(
    command_prefix="!",
    intents=intents,
    help_command=None
)

@bot.event
async def on_ready():
    # Triggered once the bot successfully connects to Discord
    print(f"Connected as {bot.user} ({bot.user.id})")

def load_cogs():
    # Automatically load all extensions from the cogs directory
    cogs_path = Path("cogs")
    if not cogs_path.exists():
        return

    for file in cogs_path.glob("*.py"):
        try:
            bot.load_extension(f"cogs.{file.stem}")
            print(f"Loaded cog: {file.stem}")
        except Exception as e:
            print(f"Failed to load cog {file.stem}: {e}")

# Load extensions before starting the bot
load_cogs()

# Start the bot
bot.run(TOKEN)