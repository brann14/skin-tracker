# engine.py - handles the website & discord bot, and most importantly the skin price tracking

# imports

import os
import sys
import functools
import secrets
import requests
import discord
import psycopg2
import psycopg2.extras
import user_agents
import json

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
DEBUG_MODE = os.getenv("DEBUG_MODE", "false").lower() == "true" # env vars are strings, "False" would be truthy

# for tracking skins
MAX_TRACKED = 5 # max tracked skins at once
DELETE_RATELIMIT = MAX_TRACKED * 2 # basicaly just double the max_tracked limit so we find a good ratelimit


# initalize the flask app
app = Flask(__name__)
app.secret_key = SESSION_SECRET

# initalize the security protocols

csp = {
    'default-src': '\'self\'',
    'script-src': ['\'self\'', 'https://jsdelivr.net', 'https://cdn.tailwindcss.com'],
    'style-src': ['\'self\'', '\'unsafe-inline\'', 'https://fonts.googleapis.com'],
    'font-src': ['\'self\'', 'https://fonts.gstatic.com']
}

Talisman(app, content_security_policy=csp)
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
    
    # calculate confidence level based on the number of other accounts that logged in from this same ip, browser and os
    confidence = 0
    for row in rows:
        confidence += 10
        if row["ip"] == ip:
            confidence += 40
            if row["browser"] == browser:
                confidence += 30
            if row["os"] == os:
                confidence += 20
                
    # calculate if the user should be denied access based on the confidence level
    deny_access = False
    deny_access_threshold = 75 # if the confidence level is above this threshold, deny access

    if confidence > deny_access_threshold:
        deny_access = True
    return confidence, deny_access # return the confidence level and whether to deny access or not

# login_required() - decorator, redirects to the sign in page if the user is not logged in
def login_required(f):
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        if 'discord_id' not in session:
            if request.path.startswith('/api/'):
                return jsonify({"error": "not logged in"}), 401 # fetch() calls want json, not the sign in page
            return redirect(url_for('sign_in'))
        return f(*args, **kwargs)
    return wrapper
    
# sync_skins() - sync ALL the skins in CS2 (keep the function due to updates), shoutout to bymykel.com
def sync_skins():
    path = os.path.join(os.path.dirname(__file__), "..", "skins.json") # skins.json is in the repo root, engine.py is in web/
    with open(path, encoding="utf-8") as f:
        skins = json.load(f) # list of every skin, one entry per skin (not per wear)

    # one row per skin per wear, the market hash name is what steam wants
    rows = []
    seen = set() # doppler phases are separate entries with the same name, steam lists them as one item
    for skin in skins:
        weapon = (skin.get("weapon") or {}).get("name") # gloves and vanilla knives are missing some of these
        pattern = (skin.get("pattern") or {}).get("name")
        rarity = (skin.get("rarity") or {}).get("name")
        for wear in skin.get("wears", []):
            market_hash_name = f"{skin['name']} ({wear['name']})"
            if market_hash_name in seen:
                continue
            seen.add(market_hash_name)
            rows.append((market_hash_name, weapon, pattern, wear["name"], skin.get("image"), rarity))
            
    # sync it to the DB
    conn = get_db()
    cursor = conn.cursor()
    psycopg2.extras.execute_values(cursor, "INSERT INTO skins (market_hash_name, weapon, name, wear, image_url, rarity) VALUES %s ON CONFLICT (market_hash_name) DO UPDATE SET image_url = EXCLUDED.image_url, rarity = EXCLUDED.rarity", rows) # one batch insert, the %s gets expanded into all the rows
    conn.commit()
    cursor.close()
    conn.close()
    return len(rows)

# fetch_steam_price() - get the median and lowest price of one skin from the steam market
# returns (median, lowest) as floats, None if steam didnt like the name, "ratelimited" on a 429 so the loop can back off
def fetch_steam_price(market_hash_name):
    url = "https://steamcommunity.com/market/priceoverview/"
    params = {
        'country': 'US',
        'currency': 1, # 1 = usd
        'appid': 730,
        'market_hash_name': market_hash_name
    }
    try:
        response = requests.get(url, params=params, timeout=10) # dont set a fake browser ua, steam 429s it, the default one is fine
    except requests.RequestException:
        return None

    if response.status_code == 429:
        return "ratelimited"
    if response.status_code != 200:
        return None

    data = response.json()
    if not data.get('success'):
        return None

    # prices come back as strings like "$12.34" or "$1,234.56", median is missing on skins with barely any listings
    def to_float(price):
        if price is None:
            return None
        return float(price.replace('$', '').replace(',', ''))

    median, lowest = to_float(data.get('median_price')), to_float(data.get('lowest_price'))
    if median is None and lowest is None:
        return None # steam says success: true even for names that dont exist, it just leaves the prices out
    return median, lowest

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

@app.route('/tracker')
@limiter.limit("10 per minute")
@login_required
def tracker():
    return render_template("tracker.html") # render the tracker page

@app.route('/denied')
def denied():
    return render_template("denied.html")

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
    confidence, deny_access = confidence_level(discord_id, real_ip, user_agent.browser.family, user_agent.os.family) # pass the discord id, ip, browser and the os to the measurement function
    
    # save it in the DB so we can use it later for notifications and more
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO users (discord_id, access_token, username, confidence_level) VALUES (%s, %s, %s, %s) ON CONFLICT (discord_id) DO UPDATE SET access_token = EXCLUDED.access_token, username = EXCLUDED.username, confidence_level = EXCLUDED.confidence_level", (discord_id, access_token, user_data.get("username"), confidence))
    conn.commit()
    cursor.close()
    conn.close()

    session['discord_id'] = discord_id

    # redirect instead of rendering here, a refresh on this url would resend the used oauth code
    if deny_access == True: # check if the deny access is true
        return redirect(url_for('denied')) # deny access if confidence is too high
    else:
        return redirect(url_for('tracker')) # log in successful
    
# tracker API routes

# search_skins() - a GET route, fetch the user's query and search the DB for it
@app.route("/api/skins", methods=["GET"])
@limiter.limit("20 per minute")
@login_required
def search_skins():
    # input handling
    q = request.args.get('q', '').strip() # get the user's input and strip it from any whitespaces
    
    # short query guard
    if len(q) < 2: # if the query is less than 2 characters, don't lookup
        return jsonify([]), 400
    
    # database logic & query
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT market_hash_name, weapon, name, wear, image_url, rarity FROM skins WHERE market_hash_name ILIKE %s LIMIT 25", (f"%{q}%",))
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    
    return jsonify(rows), 200 # return the rows
    
# all the tracked skins
@app.route("/api/tracked", methods=["GET"])
@limiter.limit("30 per minute")
@login_required
def get_tracked():
    discord_id = session['discord_id']

    # join the skin info and grab the newest price for each one
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT t.market_hash_name, t.buy_below, t.sell_above, t.created_at, s.weapon, s.name, s.wear, s.image_url, s.rarity,
            (SELECT median FROM prices p WHERE p.market_hash_name = t.market_hash_name ORDER BY fetched_at DESC LIMIT 1) AS median
        FROM tracked t
        JOIN skins s ON s.market_hash_name = t.market_hash_name
        WHERE t.discord_id = %s
        ORDER BY t.created_at
    """, (discord_id,))
    rows = cursor.fetchall()
    cursor.close()
    conn.close()

    # jsonify chokes on Decimal
    for row in rows:
        for key in ("buy_below", "sell_above", "median"):
            if row[key] is not None:
                row[key] = float(row[key])

    return jsonify(rows), 200

# track_skin() - a POST route, does a few safety checks and tracks the skin if all good
@app.route("/api/tracked", methods=["POST"])
@limiter.limit("10 per minute")
@login_required
def track_skin():
    # fetch the user's information so it can display the proper tracked items
    discord_id = session['discord_id']
    data = request.get_json() or {}
    
    # get all the item's information
    market_hash_name = data.get("market_hash_name")
    raw_buy = data.get("buy_below")
    raw_sell = data.get("sell_above")
    
    # security checks
    # check 1 - must havea a skin name and atleast one threshold set
    if not market_hash_name or (raw_buy is None and raw_sell is None):
        return jsonify({"error": "missing market_hash_name or valid thresholds"}), 400 # return an error
    
    # check 2 - try converting non-None values with float() and reject negatives
    buy_below = None
    sell_above = None
    try:
        if raw_buy is not None:
            buy_below = float(raw_buy)
            if buy_below < 0:
                return jsonify({"error": "thresholds cannot be negative"}), 400 # cannot be negative
        if raw_sell is not None:
            sell_above = float(raw_sell)
            if sell_above < 0:
                return jsonify({"error": "thresholds cannot be negative"}), 400 # cannot be negative once again
    except (ValueError, TypeError):
        return jsonify({"error": "thresholds must be numbers"}), 400 # if theresholds are not a number, return with a 400
    
    # database logic
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT 1 FROM skins WHERE market_hash_name = %s", (market_hash_name,)) # basically, a simple query that will just fetch the row with the correct market hash name
    # check if it fetched
    if not cursor.fetchone():
        cursor.close()
        conn.close()
        return jsonify({"error": "skin not found"}), 404
    # check if the user has hit the max_tracked limit
    cursor.execute("SELECT COUNT(*) FROM tracked WHERE discord_id = %s", (discord_id,))
    count = cursor.fetchone()["count"] # RealDictCursor, so no [0]
    if count >= MAX_TRACKED:
        cursor.close()
        conn.close()
        return jsonify({"error": f"limit, the user has hit their {MAX_TRACKED} (max tracked thereshold) items"}), 403

    # if all tests have passed correctly, track it
    cursor.execute("""
        INSERT INTO tracked (discord_id, market_hash_name, buy_below, sell_above) 
        VALUES (%s, %s, %s, %s) 
        ON CONFLICT (discord_id, market_hash_name) 
        DO UPDATE SET buy_below = EXCLUDED.buy_below, sell_above = EXCLUDED.sell_above
    """, (discord_id, market_hash_name, buy_below, sell_above))
    conn.commit()
    cursor.close()
    conn.close()

    return jsonify({"ok": True}), 201

# untrack_skin() - a DELETE route that untracks a skin
@app.route("/api/tracked/<path:market_hash_name>", methods=["DELETE"])
@limiter.limit(f"{DELETE_RATELIMIT} per minute")
@login_required
def untrack_skin(market_hash_name):
    # fetch the user's information (primarly discord uid)
    discord_id = session['discord_id']
    
    # database logic
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM tracked WHERE discord_id = %s AND market_hash_name = %s", (discord_id, market_hash_name)) # just delete it from the tracked table
    deleted = cursor.rowcount
    conn.commit()
    cursor.close()
    conn.close()
    if deleted == 0:
        return jsonify({"error": "tracked skin not found"}), 404 # return with a 404
    
    return jsonify({"ok": True})
    

# application runner
if __name__ == "__main__":
    # python engine.py --sync only syncs the skins and exits, run it after a case release
    if "--sync" in sys.argv:
        print(f"synced {sync_skins()} skins")
        sys.exit()
    app.run(debug=DEBUG_MODE, host="0.0.0.0", port="6032")