import orjson
import random
import asyncio
import time
from datetime import datetime
from data_dir import data_path
commandsRaw = {}

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
    'update':'updatexport',
    'mostuniform':'mostaverage',
    'synergies':'synergy',
    'a':'mostaverage',
    'commands':'help',
    'bottom':'top'
}
server_locks = {}  # str(guild_id) -> asyncio.Event

def get_server_lock(guild_id):
    sid = str(guild_id)
    if sid not in server_locks:
        server_locks[sid] = asyncio.Event()
        server_locks[sid].set()  # starts unlocked (set = free)
    return server_locks[sid]

modOnlyCommands = ['addrating','removetradepen','addredirect','removeredirect','removereleasedplayer','clearalloffers','edit', 'load', 'addgm', 'removegm', 'startdraft', 'runresignings', 'autocut', 'runfa','pausedraft','reprog','resetgamestrade','addrule','deleterule','addaward','removeaward','autofa','echo','media']

curdate = datetime.today().strftime('%Y-%m-%d')

# Retry loading servers.json — volume mount may not be ready immediately
serversList = {}

for _attempt in range(5):
    try:
        with open(data_path("servers.json"), "rb") as f:
            content = f.read()
        if content:
            serversList = orjson.loads(content)
            break
    except (FileNotFoundError, orjson.JSONDecodeError):
        pass
    time.sleep(1)

# Create a fresh configuration if none exists
if "default" not in serversList:
    print("No servers.json found - creating a new one.")

    serversList = {
        "default": {
            "name": "",
            "prefix": "-",
            "tradechannel": "",
            "draftStatus": {
                "draftRunning": False
            },
            "rookieoptions": 0.0,
            "aimedia": 0,
            "tradeapproval": "off",
            "poschanges": "on"
        }
    }

    with open(data_path("servers.json"), "wb") as f:
        f.write(orjson.dumps(serversList))

else:
    serversList["default"].setdefault("rookieoptions", 0.0)
    serversList["default"].setdefault("aimedia", 0)
    serversList["default"].setdefault("tradeapproval", "off")
    serversList["default"].setdefault("poschanges", "on")

serverExports = {}
export_last_access = {}  # str(guild_id) -> time.time() of last access
EXPORT_TTL = 30  # seconds before an idle export is evicted from RAM
MAX_CACHED_EXPORTS = 1  # keep at most 1 idle export in RAM; drafts are protected from eviction
trivias = dict()

bot = None

def getadjective():
    adjlist = ['merrily','blissfully','stupidly','gladly','lazily','resignedly','reluctantly','calmly','smartly','affectionately','casually','haphazardly','accidentally','hastily','excitedly','normally','wishfully','hesitantly','sorrowfully','allegedly']
    adjlist += ['opportunistically','strategically','carefully','boldly','rashly','shrewdly']

    return random.sample(adjlist,1)[0]

_tips_pool = None  # built lazily from _TIP_DESCRIPTIONS: list of (command, description)

# A short, footer-sized tip for every command — purpose-written to fit on one line,
# not the longer help-screen blurbs. Keyed by the bare command word; the [arg] hints
# come from the help catalog at build time. "(mod)" flags admin-only commands.
_TIP_DESCRIPTIONS = {
    # getting started / players
    'load': 'Load a BBGM export to get rolling',
    'roster': "See your team's roster",
    'standings': 'League standings at a glance',
    'stats': "A player's season stats",
    'bio': "A player's bio and vitals",
    'offer': 'Bid on a free agent',
    'lineup': 'View your starting lineup',
    'lmove': 'Slot a player into your lineup',
    'help': 'Browse every command by category',
    'ratings': "A player's full ratings + build",
    'adv': 'Advanced stats — PER, VORP, BPM',
    'hstats': "A player's year-by-year statlines",
    'cstats': "A player's career totals",
    'progs': "How a player's ratings grew each year",
    'awards': 'Every award a player has won',
    'pgamelog': "A player's game-by-game log",
    'shots': "A player's shot chart and splits",
    'nbacomp': 'Which real NBA player they resemble',
    'scout': 'An AI scouting report on a player',
    'synergy': 'How a player meshes with teammates',
    'composites': "A player's composite skill ratings",
    'lcomplete': 'What a player adds to your lineup',
    'whoidolizes': 'Who looks up to this player',
    'contracthistory': "A player's past contracts",
    'compare': "A player's closest statistical matches",
    'pcompare': 'Two players, stat for stat',
    'series': 'Playoff series history between teams',
    'trivia': 'Spin up a player trivia question',
    'answer': 'Guess the current trivia answer',
    'hint': 'Get a nudge on the trivia',
    # teams
    'sroster': 'Roster, but showing stats',
    'psroster': 'Roster with playoff stats',
    'proster': 'Roster with progression ratings',
    'picks': 'Draft picks your team owns',
    'ownspicks': "Who holds this team's original picks",
    'history': "A franchise's full history",
    'finances': 'Your cap sheet, contracts, and hype',
    'seasons': 'A team, season by season',
    'tstats': "A team's stats this season",
    'ptstats': "A team's playoff stats",
    'schedule': "What's next on the schedule",
    'sos': 'How tough the road ahead is',
    'gamelog': 'Every game result this season',
    'game': 'Recap and top scorers from a game',
    'boxscore': 'The full box score of a game',
    'capspace': 'Where your cap space went',
    'penalties': "A team's trade-penalty history",
    'synergylineups': 'Your best 5-man synergy combos',
    'tscout': 'An AI scouting report on a team',
    'tnbacomp': 'The NBA team-season yours plays like',
    # league
    'fa': 'Browse the free-agent pool',
    'pr': "This week's power rankings",
    'playoffs': 'The bracket for any season',
    'playoffpredict': 'Projected seeds and title odds',
    'matchups': 'Two teams compared head-to-head',
    'top': 'League leaders in any rating',
    'topall': 'The best across every rating',
    'leaders': "This season's stat leaders",
    'combine': "This year's draft combine numbers",
    'combineall': 'All-time draft combine records',
    'badge': 'Find every player with a badge',
    'retired': 'Recently retired players and their peaks',
    'mvp': 'The MVP race, top 10',
    'dpoy': 'The DPOY race, top 10',
    'injuries': "Who's hurt around the league",
    'deaths': "Players who've passed on",
    'summary': 'A whole season, summarized',
    'media': 'Post a league media report right here (mod)',
    'draftorder': 'The current draft order',
    'draft': "Scout this year's draft class",
    'specialists': 'Players with wild, spiky ratings',
    'mostaverage': "The league's most well-rounded players",
    'mostunbalanced': 'The most lopsided rating profiles',
    'sadprogs': 'Who fell off the hardest',
    'godprogs': 'Who leveled up the most',
    'pickvalue': 'What each draft pick is worth',
    'po': 'Every player option in the league',
    'to': 'Every team option in the league',
    'leaguesynergy': 'Lineup synergy for every team',
    'leaguebuilds': 'What playstyles fill the league',
    # free agency
    'bulkoffer': 'Offer to several free agents at once',
    'bulkoffermins': 'Auto-min-offer the top free agents',
    'offers': 'Your outstanding offers',
    'deloffer': 'Pull one of your offers',
    'clearoffers': 'Wipe all your offers',
    'viewalloffers': "See every team's offers (mod)",
    'move': 'Reorder your signing priorities',
    'tosign': "Cap how many players you'll sign",
    'resignings': 'Your pending re-signings',
    'qo': 'Send qualifying offers to your RFAs',
    'match': 'Match an offer sheet on your RFA',
    'contractrules': "Your server's contract rules",
    'addrule': 'Add a contract rule (mod)',
    'deleterule': 'Delete a contract rule (mod)',
    # draft board
    'board': 'Your draft big board',
    'add': 'Add a prospect to your board',
    'remove': 'Drop a prospect from your board',
    'dmove': 'Reorder your draft board',
    'clearboard': 'Empty your draft board',
    'bulkadd': 'Add many prospects at once',
    'auto': 'Set an autodraft formula',
    'pick': 'Make your pick on the clock',
    'pausedraft': 'Pause a live draft (mod)',
    # roster management
    'pt': "Tweak a player's minutes",
    'autosort': 'Auto-sort your roster by rating',
    'synergysort': 'Reorder your roster for synergy',
    'findsynergy': 'Find your best synergy combos',
    'resetpt': 'Reset all minutes to default',
    'changepos': "Change a player's position",
    'release': 'Cut a player from your roster',
    # coaches
    'coaches': 'Every coach and their record',
    'hirecoach': 'Hire a retired legend to coach (GM)',
    'firecoach': 'Let your coach go (GM)',
    # charts
    'proggraph': "Graph a player's rating over time",
    'progspredict': "Predict a player's career peak",
    'schart': 'Chart a stat across players over time',
    'cschart': 'Chart all-time cumulative totals',
    'leaguegraph': 'Plot every team on two stats',
    'lgoptions': 'Stat choices for leaguegraph',
    'rostergraph': 'Plot a roster on two stats',
    'rgoptions': 'Stat choices for rostergraph',
    'tcompare': 'Two teams side by side',
    # mod
    'settings': 'View and edit server settings (mod)',
    'edit': 'Change one server setting (mod)',
    'updatexport': 'Push the export to Dropbox (mod)',
    'teamlist': 'Teams and their GMs',
    'addgm': 'Assign a GM to a team (mod)',
    'removegm': 'Remove a GM (mod)',
    'assigngm': 'Auto-assign GMs by role (mod)',
    'startdraft': 'Kick off the draft (mod)',
    'runfa': 'Run free agency (mod)',
    'autofa': 'Auto-offer for thin rosters (mod)',
    'runresignings': 'Process re-signings (mod)',
    'autosign': 'Auto-sign for CPU teams (mod)',
    'autors': 'Auto re-sign for CPU teams (mod)',
    'autocut': 'Trim over-the-limit rosters (mod)',
    'addrating': "Nudge a player's ratings (mod)",
    'removereleasedplayer': "Clear a released player's deal (mod)",
    'removetradepen': "Lift a team's trade penalty (mod)",
    'resetgamestrade': 'Make everyone tradeable now (mod)',
    'reprog': 'Re-run progressions (mod)',
    'stripnames': 'Strip real names from the export (mod)',
    'addredirect': 'Add a command alias (mod)',
    'removeredirect': 'Remove a command alias (mod)',
    'echo': 'Make the bot repeat after you',
}

def _build_tips_pool():
    """Flatten every documented command into (command, short_tip) pairs.

    Tips come from _TIP_DESCRIPTIONS (footer-sized, hand-written). We show the
    bare command word — no [arg] hints — so every footer stays one tidy line;
    full syntax lives in -help. Covers the whole catalog, not just the few we
    promote, so footers teach the deep cuts too. Lazy import because help.py
    imports back into the command stack.
    """
    import help
    seen = set()
    pool = []
    for info in help.helpScreens.values():
        for cmd in info['commands']:
            base = cmd.split(' ')[0]  # the command word, without [arg] hints
            if base in seen:
                continue
            seen.add(base)
            tip = _TIP_DESCRIPTIONS.get(base)
            if tip:
                pool.append((base, tip))
    return pool

def embedFooter(guild=None):
    global _tips_pool
    if guild:
        base = f"{guild.name} {getadjective()} presents"
        prefix = serversList.get(str(guild.id), {}).get('prefix', '-')
        if _tips_pool is None:
            try:
                _tips_pool = _build_tips_pool()
            except Exception:
                _tips_pool = []
        if _tips_pool:
            cmd, desc = random.choice(_tips_pool)
            return f"{base} | \U0001f4a1 {prefix}{cmd} — {desc}"
        return base
    return 'Odle'

