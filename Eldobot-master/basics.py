import json
import orjson
import urllib.request
import shared_info
from difflib import SequenceMatcher
import random
import asyncio
import aiohttp
import aiofiles
from unidecode import unidecode
import os
import shutil
import subprocess
from io import BytesIO
import discord
import gzip
import shutil
import uuid
from data_dir import data_path


bot = shared_info.bot


def clean_priorities(db):
    for n, s in db.items():
        if "offers" not in s:
            print(f"Server {n} is missing 'offers'")
            print("Keys:", list(s.keys()))
            s["offers"] = []      # temporary fix
            continue

        offers = sorted(s["offers"], key=lambda o: o["priority"])

        teams = list(set(o["team"] for o in offers))

        for t in teams:
            pri = 1
            for o in offers:
                if o["team"] == t:
                    o["priority"] = pri
                    pri += 1

    return db





def stringify_keys(obj):
    """Recursively convert all dict keys to strings for orjson compatibility."""
    if isinstance(obj, dict):
        return {str(k): stringify_keys(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [stringify_keys(i) for i in obj]
    return obj

async def save_db_content(db, name='servers.json'):
    if name == 'servers.json' or name.endswith('servers.json'):
        db = clean_priorities(db)
        db = stringify_keys(db)
        if name == 'servers.json':
            name = data_path(name)
    # Write to temp file then atomically rename to prevent corruption.
    # Tmp name is unique per call so concurrent saves don't clobber each other.
    tmp = f"{name}.tmp.{os.getpid()}.{uuid.uuid4().hex}"
    async with aiofiles.open(tmp, 'wb') as f:
        await f.write(orjson.dumps(db, option=orjson.OPT_NON_STR_KEYS))
    os.replace(tmp, name)

async def save_db(db, name='servers.json'):
    if name == 'servers.json':
        # Backup current file before overwriting
        src = data_path('servers.json')
        dst = data_path('serversb.json')
        if os.path.exists(src) and os.path.getsize(src) > 0:
            shutil.copy2(src, dst)
        name = data_path(name)

    await asyncio.create_task(save_db_content(db, name))

def load_db(name='servers.json'):
    if name == 'servers.json':
        name = data_path(name)
    with open(name, 'rb') as f:
        db = orjson.loads(f.read())
    return(db)

import dropbox
'''async def update_export_content(text, message):
    await message.channel.send('Uploading your export to dropbox...')
    """
    Uploads a file to Dropbox and returns a shareable link.
    
    :param file_path: Local path to the file to be uploaded.
    :param dest_path: Path in Dropbox where the file will be saved.
    :param access_token: OAuth2 access token for Dropbox.
    :return: Shareable link to the uploaded file.
    """

        path_to_file = data_path(f'exports/{message.guild.id}-export.json')
    # Upload the file
    with open(path_to_file, "rb") as f:
        dbx.files_upload(f.read(), f'/exports/{message.guild.id}-export.json')


    # Get a shareable link

    try:
        shared_link_metadata = dbx.sharing_create_shared_link_with_settings(f'/exports/{message.guild.id}-export.json')
        url = shared_link_metadata.url
    except dropbox.exceptions.ApiError as e:
        # If a shared link already exists, get the existing link
        if isinstance(e.error, dropbox.sharing.CreateSharedLinkWithSettingsError) and \
           e.error.is_shared_link_already_exists():
            links = dbx.sharing_list_shared_links(path=f'/exports/{message.guild.id}-export.json').links
            if len(links) > 0:
                url = links[0].url


    
    text = '**Your dropbox link:** ' + url.replace('www.', 'dl.')
    await message.channel.send(text)

async def update_export(text, message):
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, update_export_content, text, message)'''

# Dropbox credentials — supply via environment variables or dropbox.txt (not committed)
ACCESS_TOKEN = 'sl.wrong-'
REFRESH_TOKEN = os.environ.get("DROPBOX_REFRESH_TOKEN")
if not REFRESH_TOKEN:
    try:
        with open("dropbox.txt", "r") as f:
            for line in f:
                REFRESH_TOKEN = line.replace("\n", "")
    except FileNotFoundError:
        REFRESH_TOKEN = None
CLIENT_ID = os.environ.get("DROPBOX_CLIENT_ID", "")
CLIENT_SECRET = os.environ.get("DROPBOX_CLIENT_SECRET", "")


def refresh_access_token():
    global ACCESS_TOKEN, REFRESH_TOKEN
    flow = dropbox.DropboxOAuth2FlowNoRedirect(CLIENT_ID, CLIENT_SECRET, token_access_type='offline')
    print(flow)
    print(flow.start())
    dbx = dropbox.Dropbox(oauth2_refresh_token=REFRESH_TOKEN, app_key=CLIENT_ID, app_secret = CLIENT_SECRET)

    return dbx
        #dbx.users_get_current_account()
        #print("Successfully set up client!")
    #new_tokens = flow.refresh_access_token(REFRESH_TOKEN)
    #ACCESS_TOKEN = new_tokens.access_token
    #REFRESH_TOKEN = new_tokens.refresh_token

def upload_to_dropbox(path_to_file, dest_path):

    global ACCESS_TOKEN
    CHUNK_SIZE = 4 * 1024 * 1024
    dbx = dropbox.Dropbox(ACCESS_TOKEN)

    # Check if the file already exists
    def _try_delete_existing(client):
        try:
            client.files_get_metadata(dest_path)
            client.files_delete_v2(dest_path)
        except dropbox.exceptions.ApiError as e:
            if not (isinstance(e.error, dropbox.files.GetMetadataError) and e.error.is_path()):
                raise
        except dropbox.exceptions.InternalServerError:
            pass  # transient — re-upload will overwrite

    try:
        _try_delete_existing(dbx)
    except dropbox.exceptions.AuthError:
        dbx = refresh_access_token()
        _try_delete_existing(dbx)

    with open(path_to_file, "rb") as f:
        file_size = os.path.getsize(path_to_file)

        if file_size <= CHUNK_SIZE:
            dbx.files_upload(f.read(), dest_path)
        else:
            upload_session_start_result = dbx.files_upload_session_start(f.read(CHUNK_SIZE))
            session_id = upload_session_start_result.session_id
            offset = CHUNK_SIZE

            while offset < file_size:
                if file_size - offset <= CHUNK_SIZE:
                    dbx.files_upload_session_finish(f.read(CHUNK_SIZE), dropbox.files.UploadSessionCursor(session_id=session_id, offset=offset), dropbox.files.CommitInfo(path=dest_path))
                else:
                    dbx.files_upload_session_append_v2(f.read(CHUNK_SIZE), dropbox.files.UploadSessionCursor(session_id=session_id, offset=offset))
                offset += CHUNK_SIZE

    url = None
    try:
        shared_link_metadata = dbx.sharing_create_shared_link_with_settings(dest_path)
        url = shared_link_metadata.url
    except dropbox.exceptions.AuthError as e:
        dbx = refresh_access_token()
        return upload_to_dropbox(path_to_file, dest_path)
    except dropbox.exceptions.ApiError as e:
        if isinstance(e.error, dropbox.sharing.CreateSharedLinkWithSettingsError) and e.error.is_shared_link_already_exists():
            links = dbx.sharing_list_shared_links(path=dest_path).links
            if len(links) > 0:
                url = links[0].url

    if url is None:
        # Fallback: fetch existing shared link if one exists from a prior upload
        try:
            links = dbx.sharing_list_shared_links(path=dest_path).links
            if links:
                url = links[0].url
        except Exception:
            pass

    return url

def _upload_export_gzipped(path_to_file, guild_id):
    """Gzip-compress the export JSON then upload as .json.gz to Dropbox.

    BBGM JSON compresses 5-8x (lots of repeated keys / numeric runs),
    so this is the highest-leverage way to keep Dropbox under quota.
    Also cleans up the legacy uncompressed .json file at the same base
    path so we don't keep both versions around.
    """
    import tempfile as _tempfile
    gz_dest = f"/exports/{guild_id}-export.json.gz"
    legacy_dest = f"/exports/{guild_id}-export.json"
    with _tempfile.NamedTemporaryFile(suffix='.json.gz', delete=False) as tmp:
        gz_temp = tmp.name
    try:
        with open(path_to_file, 'rb') as src, gzip.open(gz_temp, 'wb', compresslevel=6) as dst:
            shutil.copyfileobj(src, dst)
        url = upload_to_dropbox(gz_temp, gz_dest)
        # Best-effort purge of the older uncompressed file from prior versions
        try:
            global ACCESS_TOKEN
            dbx = dropbox.Dropbox(ACCESS_TOKEN)
            try:
                dbx.files_delete_v2(legacy_dest)
            except dropbox.exceptions.AuthError:
                dbx = refresh_access_token()
                try:
                    dbx.files_delete_v2(legacy_dest)
                except Exception:
                    pass
            except dropbox.exceptions.ApiError:
                pass  # didn't exist — fine
        except Exception:
            pass
        return url
    finally:
        try:
            os.unlink(gz_temp)
        except Exception:
            pass


async def update_export_content(message):

    await message.channel.send('Uploading your export to dropbox...')
    path_to_file = data_path(f'exports/{message.guild.id}-export.json')
    loop = asyncio.get_event_loop()
    try:
        url = await loop.run_in_executor(None, _upload_export_gzipped, path_to_file, message.guild.id)
    except dropbox.exceptions.ApiError as e:
        # Detect storage-full so we surface a clear message and don't
        # let Sentry get spammed with the same infra issue from every
        # guild that tries to update.
        err_text = str(e).lower()
        if 'insufficient_space' in err_text:
            await message.channel.send(
                "❌ Dropbox storage is currently full — the bot's linked Dropbox account "
                "has hit its quota, so no exports can upload right now. Ping the bot "
                "maintainer to free space or upgrade the plan."
            )
            return
        raise
    if not url:
        await message.channel.send('Dropbox upload finished but no shareable link was returned. Try again in a moment.')
        return
    text = '**Your dropbox link:** ' + url.replace('www.', 'dl.')
    await message.channel.send(text)

async def update_export(text, message):
    if message.content.__contains__("updateexport"):
        await message.channel.send("WARNING: The call 'updateexport' is depreciated. The correct way to call this is 'updatexport' (with just one e)")
    print("updating export")
    asyncio.create_task(update_export_content(message))

async def load_export_content(text, message):
    if len(text) == 1:
        await message.channel.send('Please provide an export URL.')
    else:
        url = text[1]
        exportCheck = url.startswith('http')
        if exportCheck:
            await message.channel.send('Loading export...')
            try: 
                async with aiohttp.ClientSession() as session:
                    async with session.get(url) as response:
                        name = data_path(f'exports/{message.guild.id}-export.json')
                        if ".gz" in url:
                            name = data_path(f'exports/{message.guild.id}-export.gz')
                        async with aiofiles.open(name, 'wb') as f:
                            while True:
                                chunk = await response.content.read(1024)
                                if not chunk:
                                    break
                                await f.write(chunk)
                if str(message.guild.id) in  shared_info.serverExports:
                    del shared_info.serverExports[str(message.guild.id)]
                print("here")
                
                if ".gz" in url:
                    gz_path = data_path(f'exports/{message.guild.id}-export.gz')
                    # Reject obvious non-gzip payloads (e.g. an HTML error page returned
                    # by the upstream host) up front so we don't spam Sentry with the
                    # generic BadGzipFile from deep inside gzip.read.
                    with open(gz_path, 'rb') as f_check:
                        magic = f_check.read(2)
                    if magic != b'\x1f\x8b':
                        await message.channel.send(
                            "That .gz link didn't return a gzipped file (got HTML or an error page). "
                            "Double-check the URL — it may have expired or require login."
                        )
                        return
                    with gzip.open(gz_path, 'rb') as f_in:
                        with open(data_path(f'exports/{message.guild.id}-export.json'), 'wb') as f_out:
                            shutil.copyfileobj(f_in, f_out)
                async with aiofiles.open(data_path(f'exports/{message.guild.id}-export.json'), 'rb') as f:
                    shared_info.serverExports[str(message.guild.id)]= orjson.loads(await f.read())

                # Strip any legacy build-classifier caches that earlier versions
                # may have written into the export dict — they bloated saved files.
                try:
                    import player_builds
                    player_builds._purge_legacy_export_caches(shared_info.serverExports[str(message.guild.id)])
                except Exception:
                    pass

                #del(data)
                #brief initialization on exports
                players = shared_info.serverExports[str(message.guild.id)]['players']
                for p in players:
                    p['stats'].sort(key=lambda s: s['season'] if isinstance(s['season'], int) else int(s['season']))
                    p['ratings'].sort(key=lambda r: r['season'] if isinstance(r['season'], int) else int(r['season']))
                    p['contract'].update({'amount':round(p['contract']['amount'],0)})
                   
                path_to_file = data_path(f'exports/{str(message.guild.id)}-export.json')
                await save_db(shared_info.serverExports[str(message.guild.id)], path_to_file)
                await message.channel.send('Complete!')
                
                # AI media reports are posted on demand with -media (mod only),
                # in whatever channel the mod runs it, not on export load.
            except Exception as e:
                print(f"An error: {e}")
                try:
                    import sentry_sdk
                    with sentry_sdk.push_scope() as scope:
                        scope.set_tag("subsystem", "load_export")
                        scope.set_tag("guild_id", str(message.guild.id) if message.guild else "unknown")
                        sentry_sdk.capture_exception(e)
                except Exception:
                    pass
                await message.channel.send("There was an error loading that file. Ensure it's a valid JSON or try another link.")
        else:
            await message.channel.send('Invalid link.')

async def load_export(text, message):
    print("loading")
    loop = asyncio.get_event_loop()
    await loop.create_task(load_export_content(text, message))

def find_match(input, export, fa=False, activeOnly=False, settings = None):
    bestMatch = 0
    players = export['players']
    nicks = {}
    if settings and isinstance(settings, dict):
        nicks = settings.get('nickname', {})
    for p in players:
        try:
            p['tid'] = int(p['tid'])
        except (TypeError, ValueError):
            continue
        playerName = unidecode(p['firstName'] + ' ' + p['lastName'])
        matchScore = SequenceMatcher(a=str.lower(input), b=str.lower(playerName.replace('.', '')))
        matchScore = float(matchScore.ratio())
        # Check nickname match
        nick = nicks.get(str(p['pid']), '')
        if nick:
            nickScore = SequenceMatcher(a=str.lower(input), b=str.lower(nick)).ratio()
            if nickScore > matchScore:
                matchScore = nickScore
        try:
            if p['ratings'][-1]['ovr'] > 50:
                matchScore += (random.randint(7500,10000))/100000000 #random player if blank input
            else:
                matchScore += (random.randint(1,10000))/100000000 #random player if blank input
        except Exception:

            matchScore += (random.randint(1,10000))/100000000
        if p['tid'] > -1 or p['tid'] == -2:
            matchScore += 0.1
            if export['gameAttributes']['phase'] == 5:
                if p['tid'] == -2:
                    matchScore += 0.15
        #adding later for FA
        if fa:
            if p['tid'] == -1:
                matchScore += 0.5
        if activeOnly:
            if p['tid'] > -2:
                matchScore += 0.5
        if input.replace(' ', '') == playerName.replace(' ', ''):
            matchScore += 1
       
        for y in range (1,5):
            for x in range (0,len(input)-y):
                tocomp = input[x:x+y]
                if playerName.lower().__contains__(tocomp):
                    matchScore += 0.05*y

        if matchScore > bestMatch:
            bestMatch = matchScore
            winningPlayer = p['pid']
    return winningPlayer

def group_numbers(numbers):
    if numbers == []:
        return 'No Experience'
    else:
        numbers.sort()
        groups = []
        start = numbers[0]
        end = numbers[0]
        for i in range(1, len(numbers)):
            if numbers[i] == end + 1:
                end = numbers[i]
            else:
                if start == end:
                    groups.append(str(start))
                else:
                    groups.append(str(start) + '-' + str(end))
                start = numbers[i]
                end = numbers[i]
        if start == end:
            groups.append(str(start))
        else:
            groups.append(str(start) + '-' + str(end))
        return ', '.join(groups)

def rating_names(text):
    text = str.lower(text)
    ratingTerms = {
        "hgt": ['height', 'tall', 'tallness', 'size', 'stature',],
        "stre": ['strength', 'muscle', 'toughness', 'fat', 'big', 'heavy', 'wide'],
        "spd": ['speed', 'quick', 'quickness', 'rapidity', 'velocity', 'agility', 'acceleration'],
        "jmp": ['jump', 'jumping', 'vertical', 'leap', 'leaping', 'bounce', 'hop'],
        "endu": ['endurance', 'stamina', 'cardio', 'resilience', 'sustainability'],
        "ins": ['inside', 'post', 'interior', 'paint', 'lowpost', 'closerange'],
        "dnk": ['dunks', 'layups', 'dunks/layups', 'slashing', 'driving', 'finishing'],
        "ft": ['freethrows', 'freethrow', 'foulshot', 'free'],
        "fg": ['midrange', '2pt', 'twopoint', 'twopointers', 'two', '2p'],
        "tp": ['threepoint', 'outside', 'range', '3pt', 'three', 'triple', '3p'],
        "oiq": ['offensiveiq', 'offense', 'offensiveawareness'],
        "diq": ['defensiveiq', 'defense', 'defensiveawareness'],
        "drb": ['dribbling', 'handling', 'handles', 'control', 'ballhandling'],
        "pss": ['passing', 'pass', 'playmaking', 'pas', 'assist'],
        "reb": ['rebounding', 'boards', 'board', 'rebound', 'boxout', 'box']
    }
    for r, t in ratingTerms.items():   
        for thing in t:
            if text == thing:
                text = r
    return text

def get_setting_value(setting, export, year=None):
    settingData = export['gameAttributes'][setting]
    if year == None:
        year = export['gameAttributes']['season']
    value = None
    if isinstance(settingData, list):
        if isinstance(settingData[0], dict):
            for s in settingData:
                if s['start'] <= int(year):
                    value = s['value']
        else:
            value = settingData
    else: value = settingData
    return value


def find_pick_info(text, export):
    text = str.lower(text)
    #say for instance '2121 2nd round pick (NYC)'
    #find the round
    pickData = {
        "round": None,
        "year": None,
        "tid": None
    }
    roundTerms = {
        1: ['first', '1st', 'round 1', ' 1 round', 'rd 1', ' 1 rd'],
        2: ['second', '2nd', 'round 2', ' 2 round', 'rd 2', ' 2 rd'],
        3: ['third', '3rd', 'round 3', ' 3 round', 'rd 3', ' 3 rd'],
        4: ['fourth', '4th', 'round 4', ' 4 round', 'rd 4', ' 4 rd'],
        5: ['fifth', '5th', 'round 5', ' 5 round', 'rd 5', ' 5 rd'],
        6: ['sixth', '6th', 'round 6', ' 6 round', 'rd 6', ' 6 rd'],
        7: ['seventh', '7th', 'round 7', ' 7 round', 'rd 7', ' 7 rd'],
        8: ['eighth', '8th', 'round 8', ' 8 round', 'rd 8', ' 8 rd'],
        9: ['ninth', '9th', 'round 9', ' 9 round', 'rd 9', ' 9 rd']
    }
    rounds = get_setting_value('numDraftRounds', export)
    if rounds > 9:
        for i in range(10, rounds):
            roundTerms[i] = [str(i), 'round ' + str(i), str(i) + ' round', 'rd ' + str(i), str(i) + ' rd']
    for roundNum, roundTexts in roundTerms.items():
        for txt in roundTexts:
            if txt in text:
                pickData['round'] = roundNum
    #find the year
    for i in range(0, 3000):
        if '' + str(i) + '' in text:
            pickData['year'] = i
    #find the team
    teams = export['teams']
    #first searches for parens

    for t in teams:
        if "(" in text and ")" in text: 
            text_b = text.split("(")[1].split(")")[0]
            for t in teams:
                if str.lower(t['abbrev']) == text_b.lower():
                    pickData['tid'] = t['tid']
    if pickData["tid"] is None:
        for t in teams:
            if (str.lower(t['abbrev']) in text or str.lower(t['region']) in text or str.lower(t['name']) in text.replace('round', '').replace('pick', '')):
                pickData['tid'] = t['tid']
    return pickData

from simpleeval import SimpleEval

def calculate_formula(p, season, formula):
    age = season - p['born']['year']
    r = p['ratings'][-1]
    
    # Create context dictionary with all variables
    context = {
        'age': age,
        'hgt': r['hgt'],
        'stre': r['stre'],
        'spd': r['spd'],
        'jmp': r['jmp'],
        'endu': r['endu'],
        'ins': r['ins'],
        'dnk': r['dnk'],
        'fg': r['fg'],
        'ft': r['ft'],
        'tp': r['tp'],
        'oiq': r['oiq'],
        'diq': r['diq'],
        'drb': r['drb'],
        'pss': r['pss'],
        'reb': r['reb'],
        'ovr': r['ovr'],
        'pot': r['pot']
    }
    
    # Create SimpleEval instance with safe functions
    s = SimpleEval()
    s.names = context
    
    # Add safe math functions that formulas use
    s.functions['max'] = max
    s.functions['min'] = min  
    s.functions['abs'] = abs
    
    # Use simpleeval instead of eval - safe by default!
    # SimpleEval raises FeatureNotAvailable for unsupported syntax (lists,
    # dicts, etc.). Treat any eval failure as "this player can't be scored
    # by this formula" rather than crashing the entire command.
    try:
        value = s.eval(formula)
    except Exception:
        value = 0
    return value

def formula_ranking(players, season, formula):
    playerList = []
    for p in players:
        value = calculate_formula(p, season, formula)
        playerList.append([p['pid'], value])
    playerList.sort(key=lambda p: p[1], reverse=True)
    
    return playerList

def team_mention(message, teamName, abbrev, emoji_add= True):


    role = discord.utils.get(message.guild.roles, name=teamName)
    for role2 in message.guild.roles:

        if role2.name.replace(" ","").lower() == teamName.replace(" ","").lower():
            
            role = role2
    if role is not None:
        roleMention = role.mention
    else:
        # Role does not exist, so just use the team name
        roleMention = teamName
    emoji = discord.utils.get(message.guild.emojis, name=str.lower(abbrev))
    if emoji is not None and emoji_add:
        teamText = f"{roleMention} {emoji}"
    else:
        teamText = roleMention
    return teamText

def rookie_salary(pick, serverExport):
    draftPicks = serverExport['draftPicks']
    players = serverExport['players']
    season = serverExport['gameAttributes']['season']
    totalPicks = 0
    for dpick in draftPicks:
        if dpick['round'] == 1 and dpick['season'] == season:
            totalPicks += 1
    for p in players:
        if p['draft']['year'] == season and p['draft']['round'] == 1:
            totalPicks += 1

    topRookieSalary = (serverExport['gameAttributes']['draftPickAutoContractPercent']/100)*serverExport['gameAttributes']['maxContract']
    minContract = serverExport['gameAttributes']['minContract']
    salary = topRookieSalary*(1-pick/totalPicks)+ minContract*(pick/totalPicks)
    return round(salary)
    
def get_nested_value(dct, keys):
    #Retrieve a value from a nested dictionary using a list of keys.
    for key in keys:
        if key in dct:
            dct = dct[key]
        else:
            return None
    return dct
    
def player_list_embed(playerList, pageNum, season, sortBy, reverse=True, draft=False):
    values = ['ovr', 'pot', 'hgt', 'stre', 'spd', 'jmp', 'endu', 'ins', 'dnk', 'ft', 'fg', 'tp', 'oiq', 'diq', 'drb', 'pss', 'reb']
    # Coalesce missing/non-numeric values to a sentinel so sort doesn't
    # TypeError when a player has a missing rating / nested value (happens in
    # mid-season imports and ratingless leagues). Coerce to float so Decimal
    # stats (pstats returns decimal.Decimal) sort numerically instead of all
    # collapsing to the sentinel — which silently left leaders unsorted.
    def _safe(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return float('-inf') if reverse else float('inf')
    if isinstance(sortBy, str):
        sortBy = rating_names(sortBy)
        if str.lower(sortBy) in values:
            sortBy = str.lower(sortBy)
            playerList.sort(key=lambda o: _safe(o['ratings'].get(sortBy)), reverse=reverse)
        else:
            sortBy = 'ovr'
            playerList.sort(key=lambda o: _safe(o['ratings'].get(sortBy)), reverse=reverse)
    else:
        playerList.sort(key=lambda p: _safe(get_nested_value(p, sortBy)), reverse=reverse)
    
    totalPages, remainder = divmod(len(playerList), 12)
    totalPages += 1
    playerList = playerList[((pageNum-1)*12):(pageNum*12)]
    commandText = ''
    number = (pageNum-1)*12 + 1
    for f in playerList:
        if draft:
            line = f"- ``R{f['draftRound']} P{f['draftPick']}``. {f['position']} **{f['name']}** - {f['draftYear'] - f['born']} yo {f['draftRating']}"
            if isinstance(sortBy, str):
                line += f": **{f['ratings'][sortBy]} {str.upper(sortBy)}**"
            commandText += line + '\n'
        else:
            

            line = f"- ``{number}``. {f['position']} **{f['name']}** - {season - f['born']} yo {f['ovr']}/{f['pot']} {f['skills']}"
            if isinstance(sortBy, str):
                line += f" **{f['ratings'][sortBy]} {str.upper(sortBy)}**"
            else:
                if sortBy != ['value']:
                    line +=  f": **{get_nested_value(f, sortBy)}**"
            commandText += line + '\n'
            number += 1
    
    commandText += '\n' + f"*{totalPages} total pages.*"
    if isinstance(sortBy, str):
        return [commandText, str.upper(sortBy), totalPages]
    else:
        return [commandText, str(sortBy[-1]), totalPages]

async def resign_odds(playerPrices, years, offerAmount):
    if int(years) in playerPrices:
        askingPrice = playerPrices[int(years)]
        offerRatio = float(offerAmount) / (askingPrice/1000)
        if offerRatio >= 1:
            probability = 1
        else:
            if offerRatio > 0.5:
                probability = ((offerRatio-0.5)/0.5)**2
            else:
                probability = 0
    else:
        probability = 0
    return probability

import copy
async def release_player(pid, message, commandInfo, updateexport = True,export = None):
    serverId = message.guild.id
    if export is None:
        if str(serverId) in  shared_info.serverExports:
            export = shared_info.serverExports[str(serverId)]
        else:
            await message.channel.send("No export detected, which is weird")
            
    players = export['players']
    events = export['events']
    season = export['gameAttributes']['season']
    teams = export['teams']
    for p in players:
        if p['pid'] == pid:
            playerName = p['firstName'] + ' ' + p['lastName']
            age = season - p['born']['year']
            ovr = p['ratings'][-1]['ovr']
            pot = p['ratings'][-1]['pot']
            serverSettings = shared_info.serversList[str(commandInfo['serverId'])]
            if 'PO' in serverSettings:
                if pid in serverSettings['PO']:
                    del serverSettings['PO'][pid]
                if str(pid) in serverSettings['PO']:
                    del serverSettings['PO'][str(pid)]
            if 'TO' in serverSettings:
                if pid in serverSettings['TO']:
                    del serverSettings['TO'][pid]
                if str(pid) in serverSettings['TO']:
                    del serverSettings['TO'][str(pid)]
            await save_db(shared_info.serversList)
            tid = copy.deepcopy(p['tid'])
            for t in teams:
                if t['tid'] == tid:
                    abbrev = t['abbrev']
                    teamName = t['region'] + ' ' + t['name']
            newEvent = {
                'type': 'release',
                'pids': [pid],
                'tids': [tid],
                'season': season,
                'eid': events[-1]['eid']+1,
                'text': f'The <a href="/l/20/roster/{abbrev}/{season}">{teamName}</a> released <a href="/l/20/player/{pid}">{playerName}</a>.'
            }
            events.append(newEvent)
            transaction = {
                "season": export['gameAttributes']['season'],
                "phase": export['gameAttributes']['phase'],
                "tid": tid,
                "type": "release"}
            try:
                p['transactions'].append(transaction)
            except:
                p['transactions'] = []
                p['transactions'].append(transaction)
            if p['draft']['year'] != season:
                if p['draft']['year'] == season - 1 and export['gameAttributes']['phase'] == 0:
                    p['salaries'] = []
                else:
                    newRelease = {
                        'pid': p['pid'],
                        'tid': tid,
                        'contract': copy.deepcopy(p['contract'])
                    }
                    try: newRelease['rid'] = export['releasedPlayers'][-1]['rid'] + 1
                    except: newRelease['rid'] = 0
                    try: export['releasedPlayers'].append(newRelease)
                    except:
                        export['releasedPlayers'] = []
                        export['releasedPlayers'].append(newRelease)
            else:
                p['salaries'] = []
            p['tid'] = -1
            p['contract']['amount'] == export['gameAttributes']['minContract']
            p['contract']['exp'] = season+1

            text = f">>> **Release** \n -- \n The {team_mention(message, teamName, abbrev)} release **{playerName}** ({age} yo {ovr}/{pot}). \n --"
            try:
                channelId = int(shared_info.serversList[str(serverId)]['releasechannel'].replace('<#', '').replace('>', ''))
                channel = shared_info.bot.get_channel(channelId)
            except Exception:
                channel = message.channel
            if isinstance(channel, discord.TextChannel):
                # Send the message to the channel
                await channel.send(text)
                if updateexport:
                    path_to_file = data_path(f'exports/{serverId}-export.json')
                    await save_db(export, path_to_file)
                else:
                    return export
            else:
                if errorSent == False:
                    message.channel.send('Release still executed.')
                    errorSent = True





    
