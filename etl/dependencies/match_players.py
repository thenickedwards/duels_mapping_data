import re
import unicodedata
from collections import defaultdict
from difflib import SequenceMatcher

'''
FBref and the MLSPA name the same footballer differently. FBref publishes the name a
player is known by; the MLSPA publishes the name on the contract. So Evander is
'Evander da Silva Ferreira', Klauss is 'João Klauss de Mello', and Dave Romney is
'David Romney'. Neither source carries an id the other shares, so salaries are joined
to Schmetzer Scores by name within a club, working from the strictest rule to the
loosest and recording which rule fired so any match can be audited later.
'''

# Suffixes and particles that one source prints and the other drops
NAME_SUFFIXES = re.compile(r'\b(jr|sr|ii|iii|iv|junior|filho|neto)\b\.?')
NAME_PARTICLES = {'de', 'da', 'do', 'dos', 'das', 'del', 'della', 'di', 'du',
                  'van', 'von', 'der', 'den', 'la', 'le', 'el', 'al'}

# Tiers are ordered strictest first; every player is tried at each tier in turn.
MATCH_TIERS = [
    'exact_name_club',
    'exact_name',
    'token_subset_club',
    'surname_club',
    'token_overlap_club',
    'fuzzy_club',
]

FUZZY_CUTOFF = 0.84


def normalize_player_name(name):
    """ Take in a player name, return it casefolded and stripped of accents, nicknames and punctuation. """
    if not name:
        return ''
    # Decompose accents then drop the combining marks: 'Gómez' -> 'Gomez'
    decomposed = unicodedata.normalize('NFKD', str(name))
    stripped = ''.join(c for c in decomposed if not unicodedata.combining(c)).lower()
    stripped = re.sub(r'"[^"]*"', ' ', stripped)  # Quoted nicknames: Mohammed "Mo" Adams
    stripped = NAME_SUFFIXES.sub(' ', stripped)
    stripped = re.sub(r'[^a-z ]', ' ', stripped)

    return ' '.join(stripped.split())


def name_tokens(normalized_name):
    """ Take in a normalized name, return its meaningful tokens (particles and initials dropped). """
    return [t for t in normalized_name.split() if t not in NAME_PARTICLES and len(t) > 1]


def _unique(candidates):
    """ Take in a list of candidate salary rows, return the only one or None if it is not unique. """
    return candidates[0] if len(candidates) == 1 else None


def _best_fuzzy(normalized_name, candidates):
    """ Take in a name and candidate salary rows, return the closest match above the cutoff. """
    best, best_ratio = None, FUZZY_CUTOFF
    for candidate in candidates:
        ratio = SequenceMatcher(None, normalized_name, candidate['normalized_name']).ratio()
        if ratio > best_ratio:
            best, best_ratio = candidate, ratio
    return best


def match_players_to_salaries(players, salaries, verbose=1):
    '''
    This function accepts a list of player dicts (id, player_name, squad) and a list of
    salary dicts (a stable 'key', player name parts and crosswalked 'squad'), matches
    each player to at most one salary row, and returns a dict of
    player id -> {'salary_key': ..., 'match_tier': ...} alongside a tier tally.
    '''
    for salary in salaries:
        salary['normalized_name'] = normalize_player_name(
            f"{salary.get('first_name') or ''} {salary.get('last_name') or ''}")
        salary['tokens'] = name_tokens(salary['normalized_name'])

    by_name = defaultdict(list)
    by_squad = defaultdict(list)
    for salary in salaries:
        by_name[salary['normalized_name']].append(salary)
        if salary.get('squad'):
            by_squad[salary['squad']].append(salary)

    remaining = []
    for player in players:
        normalized = normalize_player_name(player['player_name'])
        remaining.append({
            'id': player['id'],
            'squad': player.get('squad'),
            'normalized_name': normalized,
            'tokens': name_tokens(normalized),
        })

    matches = {}
    claimed = set()
    tally = defaultdict(int)

    for tier in MATCH_TIERS:
        still_unmatched = []
        for player in remaining:
            squad_pool = [s for s in by_squad.get(player['squad'], []) if s['key'] not in claimed]
            name_pool = [s for s in by_name.get(player['normalized_name'], []) if s['key'] not in claimed]
            tokens = set(player['tokens'])

            if tier == 'exact_name_club':
                match = _unique([s for s in squad_pool if s['normalized_name'] == player['normalized_name']])
            elif tier == 'exact_name':
                match = _unique(name_pool)
            elif tier == 'token_subset_club':
                # FBref's short name is a subset of the MLSPA's legal name
                match = _unique([s for s in squad_pool if tokens and tokens <= set(s['tokens'])])
            elif tier == 'surname_club':
                match = _unique([s for s in squad_pool
                                 if player['tokens'] and s['tokens']
                                 and player['tokens'][-1] == s['tokens'][-1]])
            elif tier == 'token_overlap_club':
                match = _unique([s for s in squad_pool if tokens & set(s['tokens'])])
            elif tier == 'fuzzy_club':
                match = _best_fuzzy(player['normalized_name'], squad_pool)
            else:
                match = None

            if match is None:
                still_unmatched.append(player)
                continue

            matches[player['id']] = {'salary_key': match['key'], 'match_tier': tier}
            claimed.add(match['key'])
            tally[tier] += 1
        remaining = still_unmatched

    if verbose >= 1:
        matched = len(matches)
        total = matched + len(remaining)
        pct = (100.0 * matched / total) if total else 0.0
        print(f'Matched {matched} of {total} players to salary records ({pct:.1f}%)')
        for tier in MATCH_TIERS:
            if tally[tier]: print(f'    {tier}: {tally[tier]}')
        if remaining: print(f'    unmatched: {len(remaining)}')
    if verbose >= 2:
        for player in remaining: print(f"    no salary found for: {player['normalized_name']} ({player['squad']})")

    return matches, dict(tally)
