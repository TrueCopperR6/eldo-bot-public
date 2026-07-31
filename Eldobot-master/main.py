from re import L
import os
import sentry_sdk

def _sentry_before_send(event, hint):
    """Drop infrastructure noise (Discord permission errors, Dropbox 5xx).
    These are environmental, not code bugs, and flood the inbox."""
    exc_info = hint.get('exc_info') if hint else None
    if exc_info:
        exc_type, exc_value, _ = exc_info
        name = exc_type.__name__
        module = exc_type.__module__ or ''
        if module.startswith('discord') and name in ('Forbidden', 'NotFound'):
            return None
        if module.startswith('dropbox') and name in ('InternalServerError', 'ConnectionError'):
            return None
    return event

_sentry_dsn = os.environ.get("SENTRY_DSN")
if _sentry_dsn:
    sentry_sdk.init(
        dsn=_sentry_dsn,
        traces_sample_rate=0.1,
        before_send=_sentry_before_send,
    )
import discord
from discord.ext import commands
import json
import orjson
import urllib.request
import csv
import asyncio
import checks
import basics
import commands
import shared_info
from shared_info import modOnlyCommands
import os
import math
import trade_functions
import gc
from unidecode import unidecode
import commandmaster
import time
import contextlib

class _nullasync:
    async def __aenter__(self): return self
    async def __aexit__(self, *args): pass
from data_dir import data_path

import signal

_shutting_down = False

def handle_shutdown(signum, frame):
    global _shutting_down
    if _shutting_down:
        return
    _shutting_down = True
    print("Shutdown signal received, saving data before exit...")
    # Save servers.json synchronously before exiting
    try:
        import orjson as _orjson
        from basics import stringify_keys
        data = stringify_keys(shared_info.serversList)
        path = data_path('servers.json')
        tmp = path + '.tmp'
        with open(tmp, 'wb') as f:
            f.write(_orjson.dumps(data, option=_orjson.OPT_NON_STR_KEYS))
        os.replace(tmp, path)
        print("servers.json saved successfully.")
    except Exception as e:
        print(f"Error saving servers.json on shutdown: {e}")
    # Save tracking.json
    try:
        import json as _json
        tmp = data_path('tracking.json') + '.tmp'
        with open(tmp, 'w') as f:
            f.write(_json.dumps(commandmaster.tracks))
        os.replace(tmp, data_path('tracking.json'))
        print("tracking.json saved successfully.")
    except Exception as e:
        print(f"Error saving tracking on shutdown: {e}")
    print("Shutdown complete.")
    raise SystemExit(0)

signal.signal(signal.SIGTERM, handle_shutdown)
signal.signal(signal.SIGINT, handle_shutdown)

import nba_data
import nba_team_data
try:
    nba_data.load()
    print("NBA comparison data loaded.")
except Exception as e:
    print(f"NBA data not available: {e}")
try:
    nba_team_data.load()
    print(f"NBA team comparison data loaded ({len(nba_team_data._df)} team-seasons, {len(nba_team_data._stars_by_key)} star pairs).")
except Exception as e:
    print(f"NBA team data not available: {e}")

AI_COMMANDS = {'nbacomp', 'scout', 'tnbacomp', 'tscout'}
_ai_cooldowns = {}  # user_id -> last call timestamp

async def safe_send(channel, content, max_retries=3):
    """Send message with automatic retry on rate limit."""
    for attempt in range(max_retries):
        try:
            return await channel.send(content)
        except discord.errors.HTTPException as e:
            if e.status == 429:
                # Use retry_after from Discord, default to 1 second
                wait_time = getattr(e, 'retry_after', 1) or 1
                print(f"[Rate limit] Waiting {wait_time}s before retry...")
                await asyncio.sleep(wait_time)
            else:
                raise
    print(f"[Rate limit] Failed after {max_retries} retries")
    return None



#move commands to a shared place for access across the bot
shared_info.commandsRaw = commands.commandsRaw

# Only enable intents the bot actually uses to reduce memory
intents = discord.Intents.default()
intents.message_content = True  # needed to read command text
client = discord.Client(intents=intents)
shared_info.bot = client
async def process(path, g):
    f = open(path, 'rb')
    print("ended to load")
    yu = orjson.loads(f.read())
    f.close()
    if not str(g.id) in shared_info.serverExports:
        # Strip legacy build-classifier caches that earlier versions wrote into
        # the export dict on save (they bloated the on-disk file by megabytes).
        try:
            import player_builds
            player_builds._purge_legacy_export_caches(yu)
        except Exception:
            pass
        shared_info.serverExports.update({str(g.id): yu})
        print("set the db")
    else:
        print("already had it")
        del(yu)
    #return yu

#load settings db
serversList = shared_info.serversList

@client.event
async def on_error(event_method, *args, **kwargs):
    import traceback, sys
    print(f"Unhandled error in event {event_method}:", file=sys.stderr)
    traceback.print_exc()
    try:
        exc_type, exc_value, _ = sys.exc_info()
        if exc_value is not None:
            with sentry_sdk.push_scope() as scope:
                scope.set_tag("subsystem", "discord_event")
                scope.set_tag("event", event_method)
                msg = args[0] if args and hasattr(args[0], 'guild') else None
                if msg is not None:
                    scope.set_tag("guild_id", str(msg.guild.id) if msg.guild else "dm")
                    scope.set_context("message", {
                        "content": getattr(msg, 'content', '')[:500],
                        "author_id": getattr(msg.author, 'id', None) if hasattr(msg, 'author') else None,
                        "guild": msg.guild.name if msg.guild else None,
                        "channel": getattr(msg.channel, 'name', None) if hasattr(msg, 'channel') else None,
                    })
                sentry_sdk.capture_exception(exc_value)
    except Exception:
        pass

@client.event
async def on_ready():
    await client.change_presence(activity=discord.Activity(type=discord.ActivityType.watching, name='SolarBalls'))
    print('Bot connected')
    print(f'Logged in as: {client.user} (ID: {client.user.id})')
    print(f'Serving {len(client.guilds)} servers:')
    for g in client.guilds:
        print(f'  - {g.name} (ID: {g.id}, Members: {g.member_count})')
        serversList = checks.server_check(g.id, g.name)
        for item in serversList:
            #print(serversList[item])
            if 'draftStatus' in serversList[item]:
                if serversList[item]['draftStatus']['draftRunning']:
                    serversList[item]['draftStatus'].update({'draftRunning':False})

        await basics.save_db(serversList)

    # Background task: evict idle exports from RAM every 30s
    try:
        import ctypes
        _malloc_trim = ctypes.CDLL("libc.so.6").malloc_trim
    except Exception:
        _malloc_trim = None

    async def evict_idle_exports():
        while True:
            await asyncio.sleep(30)
            now = time.time()
            evicted = False
            for sid in list(shared_info.export_last_access):
                if now - shared_info.export_last_access[sid] > shared_info.EXPORT_TTL:
                    if not serversList.get(sid, {}).get('draftStatus', {}).get('draftRunning', False):
                        shared_info.serverExports.pop(sid, None)
                        shared_info.export_last_access.pop(sid, None)
                        evicted = True
            if evicted:
                gc.collect()
                if _malloc_trim:
                    _malloc_trim(0)

    client.loop.create_task(evict_idle_exports())


@client.event
async def on_guild_join(g):
    print('Joined', g.name)
    serversList = checks.server_check(g.id, g.name)
    await basics.save_db(serversList)

commandAliases = {
    "r": "ratings",
    "s": "stats",
    "b": "bio",
    "setgm": "addgm",
    'phs':'hstats',
    'phstats':'hstats',
    "ts": "tstats",
    "tsp": 'ptstats',
    "rs": "resignings",
    "runrs": "runresignings",
    "ppr":"playoffpredict",
    "cs": "cstats",
    "hs": "hstats",
    'updateexport': 'updatexport',
    'mostuniform':'mostaverage'
}

#mod only - imported from shared_info


@client.event
async def on_message(message):
    if message.guild is None:
        return
    try: prefix = serversList[str(message.guild.id)]['prefix']
    except: prefix = '-'
    if message.content.startswith(prefix):
        print("============")
        print(message.guild.name)
        print(message.channel.name)
        print(message.author.name)
        print(message.content)
        print("-------------------")
    #trade scanning - if in trade channel, just pass it along to the proper functions
    if message.guild is not None:
        if f"<#{message.channel.id}>" == serversList[str(message.guild.id)]['tradechannel'] and message.author.id != client.user.id:
            if serversList[str(message.guild.id)]['draftStatus']['draftRunning']:
                await safe_send(message.channel, "No trades during draft!")
                return
            print("here")
            g = message.guild
            sid = str(g.id)
            if not sid in shared_info.serverExports:
                # Evict oldest if at max capacity (skip servers with running drafts)
                while len(shared_info.serverExports) >= shared_info.MAX_CACHED_EXPORTS:
                    candidates = [
                        s for s in shared_info.export_last_access
                        if not serversList.get(s, {}).get('draftStatus', {}).get('draftRunning', False)
                    ]
                    if not candidates:
                        break
                    oldest = min(candidates, key=lambda s: shared_info.export_last_access[s])
                    shared_info.serverExports.pop(oldest, None)
                    shared_info.export_last_access.pop(oldest, None)
                path_to_file = data_path(f'exports/{g.id}-export.json')
                t = basics.load_db(path_to_file)
                shared_info.serverExports.update({str(g.id):t})
            shared_info.export_last_access[sid] = time.time()

            if str.lower(message.content) == 'confirm':
                if not serversList[str(message.guild.id)]['draftStatus']['draftRunning']:
                    await trade_functions.confirm_message(message)
                else:
                    await safe_send(message.channel, "No trades during draft!")
            else:
                if not serversList[str(message.guild.id)]['draftStatus']['draftRunning'] == True:
                    await trade_functions.scan_text(message.content, message)
                else:
                    await safe_send(message.channel, "No trades during draft!")
        else:
            #print(str(prefix))

            if message.content.startswith(str(prefix)):
                
                if message.author.guild_permissions.manage_messages and message.content == prefix+"forcestopdraft":
                    serversList[str(message.guild.id)]['draftStatus'].update({'draftRunning':False})
                    await safe_send(message.channel, "OK. Dont blame me if something went wrong though, as this is more like the equivalent of Danger Zone in the BBGM game.")

                text = message.content[1:].split(' ')
                command = text[0]

                command = str.lower(command)
                if not command or not command.isalpha():
                    return
                if command in commandAliases:
                    text[0] = commandAliases[command]
                    command = commandAliases[command]
                if command in commands.commands:

                    #check for mod command
                    valid = False
                    if command in modOnlyCommands:

                        if message.author.guild_permissions.manage_messages:
                            valid = True
                    else:
                        valid = True
                    if valid:
                        # AI command cooldown check (2s per user, shared across all AI commands) — before queuing
                        if command in AI_COMMANDS:
                            uid = str(message.author.id)
                            now = time.time()
                            if uid in _ai_cooldowns and now - _ai_cooldowns[uid] < 3:
                                remaining = int(3 - (now - _ai_cooldowns[uid])) + 1
                                await safe_send(message.channel, f"Please wait {remaining}s before using another AI command.")
                                return
                            _ai_cooldowns[uid] = now

                        #UPDATE EXPORT
                        server_lock = shared_info.get_server_lock(message.guild.id)
                        if not server_lock.is_set() and (not command == 'pick') and (not commands.commandsRaw[command] in ['settings','help']):
                            await safe_send(message.channel, "your command is queued, please wait")
                            try:
                                await asyncio.wait_for(server_lock.wait(), timeout=30)
                            except asyncio.TimeoutError:
                                await safe_send(message.channel, "the wait was too long, you fell out of queue")
                                return
                        print("got to command")

                        async with message.channel.typing() if command != 'startdraft' else _nullasync():
                            if not commands.commandsRaw[command] in ['analytics','settings','help']:
                                server_lock.clear()  # lock this server
                                try:
                                    g = message.guild
                                    sid = str(g.id)
                                    if not sid in shared_info.serverExports:
                                        # Evict oldest if at max capacity (skip servers with running drafts)
                                        while len(shared_info.serverExports) >= shared_info.MAX_CACHED_EXPORTS:
                                            candidates = [
                                                s for s in shared_info.export_last_access
                                                if not serversList.get(s, {}).get('draftStatus', {}).get('draftRunning', False)
                                            ]
                                            if not candidates:
                                                break
                                            oldest = min(candidates, key=lambda s: shared_info.export_last_access[s])
                                            shared_info.serverExports.pop(oldest, None)
                                            shared_info.export_last_access.pop(oldest, None)
                                        if not command == 'load': #if command is load specifically, you don't need to read an export
                                            path_to_file = data_path(f'exports/{g.id}-export.json')
                                            print("Starting to load")
                                            await process(path_to_file,g)


                                        gc.collect()
                                    shared_info.export_last_access[sid] = time.time()

                                except Exception as e:
                                    print(e)
                                    try:
                                        with sentry_sdk.push_scope() as scope:
                                            scope.set_tag("subsystem", "export_load")
                                            scope.set_tag("command", command)
                                            scope.set_tag("guild_id", str(message.guild.id))
                                            sentry_sdk.capture_exception(e)
                                    except Exception:
                                        pass
                                    await safe_send(message.channel, "You need an export to do this, but you don't have one.")


                            try:
                                await commands.commands[command](text, message)
                                commandmaster.track_command(command, message)
                            except Exception as e:
                                print(f"ERROR in command {command}: {e}")
                                import traceback
                                traceback.print_exc()
                                try:
                                    with sentry_sdk.new_scope() as scope:
                                        scope.set_tag("command", command)
                                        scope.set_tag("guild_id", str(message.guild.id) if message.guild else "dm")
                                        scope.set_context("invocation", {
                                            "command": command,
                                            "raw_text": message.content[:500],
                                            "guild": message.guild.name if message.guild else None,
                                            "guild_id": message.guild.id if message.guild else None,
                                            "channel": getattr(message.channel, 'name', str(message.channel.id)),
                                            "author_id": message.author.id,
                                        })
                                        sentry_sdk.capture_exception(e)
                                except Exception:
                                    pass
                                await safe_send(message.channel, f"Something went wrong with that command.")
                            finally:
                                server_lock.set()  # unlock this server
                        

                    else:
                        try:
                            await safe_send(message.channel, "You aren't authorized to run that command.")
                        except Exception as e:
                            print(e)
                else:
                    # Suggest similar commands using Gemini
                    try:
                        from ai_media import safe_gemini_call
                        all_commands = list(commands.commandsRaw.keys()) + list(commandAliases.keys())
                        prompt = f'The user typed the command "{command}". Valid commands are: {", ".join(all_commands)}. Which 1-3 commands did they most likely mean? Reply with ONLY the command names separated by commas, nothing else.'
                        suggestion = await safe_gemini_call(prompt)
                        if suggestion:
                            suggested = [s.strip() for s in suggestion.split(',') if s.strip() in all_commands]
                            if suggested:
                                formatted = ", ".join([f"**{prefix}{s}**" for s in suggested[:3]])
                                await safe_send(message.channel, f"Command not found. Did you mean: {formatted}?")
                            else:
                                await safe_send(message.channel, f"Command not found. Use **{prefix}help** to see available commands.")
                        else:
                            await safe_send(message.channel, f"Command not found. Use **{prefix}help** to see available commands.")
                    except Exception as e:
                        print(f"Suggestion error: {e}")
                        await safe_send(message.channel, f"Command not found. Use **{prefix}help** to see available commands.")
tk = os.environ.get("DISCORD_TOKEN")
if not tk:
    f = open("token.txt","r")
    for line in f:
        tk = line.replace("\n","")
    f.close()
client.run(tk)
# token here
