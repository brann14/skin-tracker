# engine.py - handles the website & discord bot, and most importantly the skin price tracking

# imports

import os
import secrets
import requests
import discord
import psycopg2
import psycopg2.extras
import user_agents

from flask import Flask, render_template, request, redirect, url_for, session, jsonify
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
DISCORD_CLIENT_SECRET = os.getenv("DISCORD_CLIENT_SECRET")
DISCORD_CLIENT_ID = os.getenv("DISCORD_CLIENT_ID")
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

# get_real_ip() - get the real ip of the user
def get_real_ip():
    return request.headers.get('CF-Connecting-IP') or request.remote_addr # return the IP

# confidence_level() - measure the confidence level based on their browser, IP, operating system and other factors. this is an alt security prevention measure

def confidence_level(discord_id, ip, browser, os):
    # first of all, insert everything in DB before measurement
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO login_signals (discord_id, ip, browser, os) VALUES (%s, %s, %s, %s)", (discord_id, ip, browser, os)) # insert the values into the db first of all 
    conn.commit()
    cursor.execute("SELECT ip, browser, os FROM login_signals WHERE discord_id != %s AND ip = %s", (discord_id, ip)) # find other accounts that logged in from this same ip
    rows = cursor.fetchall()
    cursor.close()
    conn.close()

    confidence = 0
    for row in rows:
        confidence += 10
        if row["browser"] == browser and row["os"] == os:
            confidence += 40
            # more will be done later

    return confidence # return the confidence level, this is a placeholder for now, will be implemented later

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
    # get the code and state from the query parameters
    scope = "identify guilds"
    state = secrets.token_urlsafe(16)
    session['oauth_state'] = state
    
    # build the auth url
    auth_url = (
        f"https://discord.com/api/oauth2/authorize"
        f"?client_id={os.getenv('DISCORD_CLIENT_ID')}"
        f"&redirect_uri={os.getenv('DISCORD_REDIRECT_URI')}"
        f"&response_type=code"
        f"&scope={scope}"
        f"&state={state}"
    )
    
    return redirect(auth_url)

# discord login complete
@app.route('/api/discord/complete')
@limiter.limit("3 per minute") # only 3 per minute to prevent brute force attacks
def discord_login_complete():
    # pull the code and state from the query parameters
    state = request.args.get('state')
    # check if the state matches the one in the session
    if state != session.get('oauth_state'):
        return jsonify({"error": "invalid state parameter"}) # return with an error

    # security check
    real_ip = get_real_ip() # get the real ip of the user, this is a security measure to prevent abuse (will be encrypted and stored in the DB)
    user_agent = user_agents.parse(request.headers.get('User-Agent')) # parse the user agent
    
    code = request.args.get('code')
    # exchange the code for an access token
    token_url = "https://discord.com/api/oauth2/token"
    data = {
        "client_id": DISCORD_CLIENT_ID,
        "client_secret": DISCORD_CLIENT_SECRET,
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": os.getenv("DISCORD_REDIRECT_URI"),
    }
    # finally, make the request to get the access token
    response = requests.post(token_url, data=data)
    access_token = response.json().get("access_token") # convert it to JSON and get the access token 
    # GET request to fetch the users data
    user_url = "https://discord.com/api/users/@me"
    headers = {
        "Authorization": f"Bearer {access_token}"
    }
    user_response = requests.get(user_url, headers=headers)
    # and finally, the user data
    user_data = user_response.json()
    discord_id = user_data.get("id") # get the discord id from the user data
    
    # confidence level is a measure of how confident we are that the user is who they say they are, based on their username and discriminator
    confidence = confidence_level(discord_id, real_ip, user_agent.browser.family, user_agent.os.family) # pass the discord id, ip, browser and the os to the measurement function

    if confidence >= 50:
        return jsonify({"error": "login denied, alt account suspected"}) # deny access if confidence is too high
    
    # save it in the DB so we can use it later for notifications and more
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO users (discord_id, access_token, username, confidence_level) VALUES (%s, %s, %s, %s) ON CONFLICT (discord_id) DO UPDATE SET access_token = EXCLUDED.access_token, username = EXCLUDED.username, confidence_level = EXCLUDED.confidence_level", (discord_id, access_token, user_data.get("username"), confidence))
    conn.commit()
    cursor.close()
    conn.close()

    session['discord_id'] = discord_id

    return redirect(url_for('main'))

# steam API routes

@app.route("/api/price/<skin_name>")
@limiter.limit("10 per minute")
def get_skin_price(skin_name):
    # get the skin from the steam market API
    url = "https://steamcommunity.com/market/priceoverview/"
    params = {
        'country': 'US',
        'currency': 1,
        'appid': 730,
        'market_hash_name': skin_name
    }
    response = requests.get(url, params=params)
    
    data = response.json() # json the response
    
    if not data.get('success'): # if the request is unsucessful, return an error
        return jsonify({"error": "failed to retrive the price, check the skin name and try again"})
    else:
        return data # return the data if success
    
    
# application runner
if __name__ == "__main__":
    app.run(debug=DEBUG_MODE, host="0.0.0.0", port="6032")