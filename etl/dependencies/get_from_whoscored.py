import json
import os
import re
from datetime import datetime
from pathlib import Path

from pandas import DataFrame

'''
WhoScored (https://www.whoscored.com) carries the same Opta event feed FBref used to
aggregate before Opta cut Sports Reference off in January 2026. FBref's Player
Miscellaneous Stats table was a season sum of those events, so it is rebuilt here
from each match's event stream instead: one row per player per match, which the
staging load sums into a season.

Pages are fetched through soccerdata's WhoScored reader, which drives a browser,
rate-limits itself and caches every page it fetches. MLS is not one of soccerdata's
built-in leagues, so it is registered at runtime from dv_whoscored.json.

This is run by hand, never on a schedule.
'''

WHOSCORED_URL = 'https://www.whoscored.com'

# WhoScored records a starter's position per match in its own codes. FBref recorded a
# season position as GK/DF/MF/FW, so each code is folded into one of those four.
# DML/DMR are wing-backs in a back five, which FBref counted as defenders; DMC is a
# holding midfielder.
POSITION_GROUPS = {
    'GK': 'GK',
    'DC': 'DF', 'DL': 'DF', 'DR': 'DF', 'DML': 'DF', 'DMR': 'DF',
    'DMC': 'MF', 'MC': 'MF', 'ML': 'MF', 'MR': 'MF',
    'AMC': 'MF', 'AML': 'MF', 'AMR': 'MF',
    'FW': 'FW', 'FWL': 'FW', 'FWR': 'FW',
}

# The profile page's Positions line, for players who never started a match.
PROFILE_POSITION_GROUPS = {
    'Goalkeeper': 'GK',
    'Defender': 'DF',
    'Midfielder': 'MF',
    'Forward': 'FW',
}

# The columns of raw_WhoScored_mls_players_match_stats, in the order they are built
MATCH_STAT_COLUMNS = [
    'season', 'game_id', 'game_date', 'stage', 'team', 'player_id', 'player', 'position',
    'age', 'is_starter', 'minutes', 'crdy', 'crdr', 'second_crdy', 'fls', 'fld', 'off',
    'crs', 'intercept', 'tklw', 'pkwon', 'pkcon', 'og', 'recov', 'duels_won', 'duels_lost',
]


def get_WhoScored_reader(league, season, cache_dir, headless=True):
    '''
    This function accepts the league entry from dv_whoscored.json, a season and a cache
    directory, registers the league with soccerdata, and returns a WhoScored reader.
    '''
    # soccerdata reads its data directory when it is first imported, so the import
    # waits until the cache directory is known.
    cache_dir = Path(os.path.expanduser(cache_dir))
    os.environ.setdefault('SOCCERDATA_DIR', str(cache_dir.parent))
    import soccerdata
    from soccerdata import _config

    # Every soccerdata reader looks leagues up in this one dict, so adding MLS to it is
    # enough. Mutated rather than reassigned so the readers see the same object.
    _config.LEAGUE_DICT[league['key']] = {
        'WhoScored': league['whoscored_name'],
        'season_start': league['season_start'],
        'season_end': league['season_end'],
    }
    return soccerdata.WhoScored(leagues=league['key'], seasons=season,
                                data_dir=cache_dir, headless=headless)


def get_WhoScored_mls_schedule(reader, regular_season_only=True, verbose=1):
    '''
    This function accepts a WhoScored reader and returns its season's finished games as a
    DataFrame of game_id, game_date and stage.

    FBref's season tables counted the regular season only (no player there ever exceeds
    34.0 nineties), so the playoffs are dropped by default to keep seasons comparable.
    '''
    schedule = reader.read_schedule().reset_index()
    # status 6 is a finished game; anything else has no complete event stream yet
    games = schedule[schedule['status'] == 6].copy()
    # The stage is blank until a season has more than one, so a missing stage is the
    # regular season
    games['stage'] = games['stage'].fillna('Major League Soccer')
    if regular_season_only:
        games = games[~games['stage'].str.contains('Playoff', case=False)]
    games['game_date'] = games['date'].astype(str).str[:10]
    if verbose >= 1:
        print(f'Found {len(games)} finished games of {len(schedule)} scheduled')
    return games[['season', 'game_id', 'game_date', 'stage']].astype(
        {'game_id': int}).reset_index(drop=True)


def get_WhoScored_match_centre(reader, league_key, season, game_id):
    '''
    This function accepts a WhoScored reader and a game, and returns that game's match
    centre data (lineups, ages and the event stream) as a dict, or None if WhoScored
    has none. Pages are cached by soccerdata, so a finished game is fetched only once.
    '''
    url = f'{WHOSCORED_URL}/Matches/{game_id}/Live'
    filepath = reader.data_dir / 'events' / f'{league_key}_{season}' / f'{game_id}.json'
    var = "require.config.params['args'].matchCentreData"
    data = json.load(reader.get(url, filepath, var=var))
    if data is None:
        # An empty page is usually a fetch that raced the page load, so try once more
        data = json.load(reader.get(url, filepath, var=var, no_cache=True))
    return data


def _event_type(event):
    return event['type']['displayName']


def _event_outcome(event):
    return event['outcomeType']['displayName']


def _event_qualifiers(event):
    return {q['type']['displayName'] for q in event.get('qualifiers', [])}


def _clamp_minute(minute, end):
    return max(0, min(minute, end))


def parse_WhoScored_match_player_stats(match, season, game_id, game_date, stage):
    '''
    This function accepts one game's match centre data and returns a list of dicts, one
    per player in either squad, matching FBref's Player Miscellaneous Stats columns.

    Every count is a tally of that player's Opta events:
      tklw       Tackle, Successful
      intercept  Interception
      recov      BallRecovery
      duels_won  Aerial, Successful    duels_lost  Aerial, Unsuccessful
      fls / fld  Foul, Unsuccessful (committed) / Successful (drawn)
      off        OffsideGiven
      crs        Pass with the Cross qualifier (corners included, as FBref counted them)
      pkwon      Foul, Successful, with the Penalty qualifier
      pkcon      Foul, Unsuccessful, with the Penalty qualifier
      og         Goal with the OwnGoal qualifier
      crdy / crdr / second_crdy  Card events; a second yellow counts as a yellow,
                 a red and a second yellow, as FBref counted it

    Minutes follow FBref in leaving stoppage time out: a full match is 90 minutes.
    '''
    events = match.get('events', [])
    regulation_end = 120 if match.get('maxPeriod', 2) > 2 else 90
    rows = []
    for side in ('home', 'away'):
        team = match[side]
        team_id = team['teamId']

        # When each player came on and went off, in regulation minutes
        on = {p['playerId']: 0 for p in team['players'] if p.get('isFirstEleven')}
        off = {}
        by_player = {}
        for e in events:
            if e.get('teamId') != team_id or 'playerId' not in e:
                continue
            player_id = e['playerId']
            by_player.setdefault(player_id, []).append(e)
            event_type = _event_type(e)
            if event_type == 'SubstitutionOn':
                on[player_id] = _clamp_minute(e['minute'], regulation_end)
            elif event_type == 'SubstitutionOff':
                off[player_id] = _clamp_minute(e['minute'], regulation_end)
            elif event_type == 'Card' and e.get('cardType', {}).get('displayName') in ('Red', 'SecondYellow'):
                off[player_id] = _clamp_minute(e['minute'], regulation_end)

        for player in team['players']:
            player_id = player['playerId']
            if player_id not in on:
                continue  # an unused substitute
            player_events = by_player.get(player_id, [])

            def count(event_type, outcome=None, qualifier=None, without=None):
                return sum(
                    1 for e in player_events
                    if _event_type(e) == event_type
                    and (outcome is None or _event_outcome(e) == outcome)
                    and (qualifier is None or qualifier in _event_qualifiers(e))
                    and (without is None or without not in _event_qualifiers(e)))

            cards = [e.get('cardType', {}).get('displayName')
                     for e in player_events if _event_type(e) == 'Card']
            yellows, seconds, reds = cards.count('Yellow'), cards.count('SecondYellow'), cards.count('Red')

            rows.append({
                'season': season,
                'game_id': game_id,
                'game_date': game_date,
                'stage': stage,
                'team': team['name'],
                'player_id': player_id,
                'player': player['name'],
                'position': player.get('position') if player.get('isFirstEleven') else None,
                'age': player.get('age'),
                'is_starter': int(bool(player.get('isFirstEleven'))),
                'minutes': max(0, off.get(player_id, regulation_end) - on[player_id]),
                'crdy': yellows + seconds,
                'crdr': reds + seconds,
                'second_crdy': seconds,
                'fls': count('Foul', 'Unsuccessful'),
                'fld': count('Foul', 'Successful'),
                'off': count('OffsideGiven'),
                'crs': count('Pass', qualifier='Cross'),
                'intercept': count('Interception'),
                'tklw': count('Tackle', 'Successful'),
                'pkwon': count('Foul', 'Successful', qualifier='Penalty'),
                'pkcon': count('Foul', 'Unsuccessful', qualifier='Penalty'),
                'og': count('Goal', qualifier='OwnGoal'),
                'recov': count('BallRecovery'),
                'duels_won': count('Aerial', 'Successful'),
                'duels_lost': count('Aerial', 'Unsuccessful'),
            })
    return rows


def get_WhoScored_mls_player_match_stats(reader, league_key, games, verbose=1):
    '''
    This function accepts a WhoScored reader and a DataFrame of games (see
    get_WhoScored_mls_schedule), and returns one row per player per game as a DataFrame.
    A game WhoScored has no data for is reported and skipped rather than failing the run.
    '''
    rows, missing = [], []
    for i, game in enumerate(games.itertuples(index=False), start=1):
        if verbose >= 1:
            print(f'[{i}/{len(games)}] Sourcing game {game.game_id} ({game.game_date})')
        match = get_WhoScored_match_centre(reader, league_key, game.season, game.game_id)
        if not match or 'events' not in match:
            missing.append(game.game_id)
            continue
        rows.extend(parse_WhoScored_match_player_stats(
            match, int(game.season), int(game.game_id), game.game_date, game.stage))
    if missing:
        print(f'⚠️  No match data on WhoScored for {len(missing)} game(s): {missing}')
    return DataFrame(rows, columns=MATCH_STAT_COLUMNS)


def get_WhoScored_player_profile(reader, player_id):
    '''
    This function accepts a WhoScored reader and player id, and returns that player's
    profile as a dict of name, nationality, nationality_iso (the flag's ISO 3166 code,
    e.g. 'us' or 'gb-eng'), birth_date (YYYY-MM-DD) and positions, any of which may be
    None. Profiles are cached by soccerdata, so each player is fetched only once.
    '''
    from bs4 import BeautifulSoup

    url = f'{WHOSCORED_URL}/players/{player_id}/show/'
    filepath = reader.data_dir / 'players' / f'{player_id}.html'
    soup = BeautifulSoup(reader.get(url, filepath, var=None).read(), 'lxml')

    # The profile is a list of "Label: value" lines, each led by an .info-label span
    fields = {}
    for label in soup.select('.info-label'):
        key = label.get_text(strip=True).rstrip(':')
        fields[key] = label.parent.get_text(' ', strip=True)[len(label.get_text(strip=True)):].strip()

    birth_date = None
    born = re.search(r'\((\s*\d{2}-\d{2}-\d{4}\s*)\)', fields.get('Age', ''))
    if born:
        birth_date = datetime.strptime(born.group(1).strip(), '%d-%m-%Y').date().isoformat()

    nationality_iso = None
    for label in soup.select('.info-label'):
        if label.get_text(strip=True).startswith('Nationality'):
            flag = label.parent.find(class_=re.compile(r'^flg-'))
            if flag:
                nationality_iso = next(c for c in flag['class'] if c.startswith('flg-'))[4:]

    return {
        'player_id': player_id,
        'player': fields.get('Name'),
        'nationality': fields.get('Nationality'),
        'nationality_iso': nationality_iso,
        'birth_date': birth_date,
        'positions': fields.get('Positions'),
    }
