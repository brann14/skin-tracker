# engine.py - handles the website & discord bot, and most importantly the skin price tracking

# imports

import os
import secrets
import requests
import discord
import psycopg2
import psycopg2.extras

from flask import Flask, render_template, request, redirect, url_for, session
from flask_talisman import Talisman
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_cors import CORS
from discord.ext import commands
from discord import app_commands
from dotenv import load_dotenv

# load the .env
load_dotenv()

# variables

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
SESSION_SECRET = os.getenv("SECRET_KEY")
DEBUG_MODE = os.getenv("DEBUG_MODE")

# initalize the flask app
app = Flask(__name__)
app.secret_key = SESSION_SECRET

# initalize the security protocols
Talisman(app)
CORS(app)
limiter = Limiter(get_remote_address, app=app, default_limits=["200 per day", "50 per hour"])

# functions

# get the database
def get_db():
    conn = psycopg2.connect(
        host=os.getenv("DB_HOST"), # the supabase pooler host, no sane fallback so don't give it one
        port=os.getenv("DB_PORT", "5432"), # 5432 is the session pooler, 6543 is the transaction one
        database=os.getenv("DB_NAME", "postgres"), # supabase always names the db postgres
        user=os.getenv("DB_USER"), # postgres.<project-ref> when going through the pooler
        password=os.getenv("DB_PASSWORD"), # no fallback
        sslmode="require", # supabase drops plaintext connections
        cursor_factory=psycopg2.extras.RealDictCursor
    )
    return conn

# flask routes

# main route
@app.route("/")
@limiter.limit("10 per minute")
def main():
    return render_template("main.html") # render the website

# sign in so you can subscribe to the notifications so you are actually notified
@app.route('/sign-in')
@limiter.limit("5 per minute")
def sign_in():
    return render_template("sign-in.html") # render the sign in page

# api routes

# discord API routes

# discord callback route

@app.route("/api/discord/callback")
@limiter.limit("5 per minute")
def discord_sign_in():
    scope = "identify guilds"
    state = secrets.token_urlsafe(16)
    session['oauth_state'] = state
    auth_url = (
        f"https://discord.com/api/oauth2/authorize"
        f"?client_id={os.getenv('DISCORD_CLIENT_ID')}"
        f"&redirect_uri={os.getenv('DISCORD_REDIRECT_URI')}"
        f"&response_type=code"
        f"&scope={scope}"
        f"&state={state}"
    )
    return redirect(auth_url)

# steam API routes

@app.route("/api/price/<skin_name>")
@limiter.limit("10 per minute")
def get_skin_price(skin_name):
    # get the skin from the steam market API
    url = "https://steamcommunity.com"
    params = {
        'country': 'US',
        'currency': 1,
        'appid': 730,
        'market_hash_name': skin_name
    }
    
# application runner
if __name__ == "__main__":
    app.run(debug=DEBUG_MODE, host="0.0.0.0", port="6032")