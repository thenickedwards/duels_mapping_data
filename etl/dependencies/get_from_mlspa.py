import io
import re
from collections import defaultdict

import pdfplumber
import requests
from pandas import DataFrame, option_context, read_csv

'''
The MLSPA (Major League Soccer Players Association) publishes a league-wide salary
guide a couple of times a season at https://mlsplayers.org/resources/salary-guide.
Every release carries the same six facts -- first name, last name, club, position,
annual base salary, and annual guaranteed compensation -- but the delivery format
changed over time: 2024 onward is CSV, 2018-2023 is PDF. The headers of the CSVs
drift year to year and the column order of the PDFs does too, so both readers are
driven by the per-season entries in data_vars.json rather than by hardcoded layouts.
'''

# Column headers vary per release, so DataFrame columns are standardized here.
MLSPA_COLUMNS = [
    'season',
    'first_name',
    'last_name',
    'club',
    'position',
    'base_salary',
    'guaranteed_comp',
    'release_label',
    'source_url',
]

# PDF releases print positions as short codes (D, M, F, GK and hyphenated pairs).
POSITION_CODE = re.compile(r'^(GK|D|M|F)(-(GK|D|M|F))?$')
# A complete currency amount, e.g. $1,650,000.00 or $89,716
MONEY = re.compile(r'^\$[\d,]+(?:\.\d{2})?$')
# A fragment of an amount that the PDF split across words, e.g. the '8,927.00' in '$ 6 8,927.00'
MONEY_FRAGMENT = re.compile(r'^[\d,\.]+$')


def download_mlspa_release(url, verbose=1):
    """ Take in an MLSPA release URL, return the response body as bytes. """
    if verbose >= 1: print(f"Sourcing salaries from {url}")
    response = requests.get(url, timeout=60)
    response.raise_for_status()
    return response.content


def read_mlspa_salary_csv(content, column_map, verbose=1):
    """ Take in CSV bytes and the release's column map, return a DataFrame of standardized columns. """
    # utf-8-sig strips the byte order mark MLSPA's exports carry
    df = read_csv(io.BytesIO(content), encoding='utf-8-sig', dtype=str)
    # Trailing spaces show up in some headers (and club names) in the 2024 release
    df.columns = [str(c).strip() for c in df.columns]

    missing = [source for source in column_map.values() if source not in df.columns]
    if missing:
        raise ValueError(f"MLSPA CSV is missing expected column(s) {missing}; found {list(df.columns)}")

    salaries_df = DataFrame({target: df[source] for target, source in column_map.items()})
    if verbose >= 2: print(salaries_df.head())

    return salaries_df


def _extract_amounts(words):
    """ Take in one PDF line's words, return (the two amounts, the words left over).

    Amounts are reassembled left to right by x-position rather than in stream order,
    because releases disagree about both: 2018 letter-spaces its digits across several
    words AND emits the '$' after them, while 2019 suffixes every amount with ')'.
    Everything that is not part of an amount is handed back untouched, still in stream
    order, since that is the only order that keeps overlapping cells apart.
    """
    amounts = []
    current, sources = None, []

    for word in sorted(words, key=lambda w: w['x0']):
        text = word['text'].rstrip(')')
        if current is not None and MONEY_FRAGMENT.match(text):
            current += text
            sources.append(word)
            continue
        if current is not None:
            amounts.append((current, sources))
        if text.startswith('$'):
            current, sources = text, [word]
        else:
            current, sources = None, []
    if current is not None:
        amounts.append((current, sources))

    amounts = [(text, srcs) for text, srcs in amounts if MONEY.match(text)]
    consumed = {id(word) for _, srcs in amounts for word in srcs}

    return [text for text, _ in amounts], [w for w in words if id(w) not in consumed]


def _strip_club(words, club):
    """ Take in a list of words and the club name found among them, return the words without it.

    The club may be spread over several words ('New England Revolution') or run
    together with the word after it ('New England RevolutionBell'), depending on
    how the PDF spaced the cell, so both cases are peeled off here.
    """
    club_words = club.split()
    remaining = []
    i = 0
    while i < len(words):
        window = [w['text'] for w in words[i:i + len(club_words)]]
        if window == club_words:
            i += len(club_words)
            continue
        # Club run together with the following word: keep the tail as its own word
        if window[:-1] == club_words[:-1] and window and window[-1].startswith(club_words[-1]):
            tail = window[-1][len(club_words[-1]):]
            if tail:
                last = words[i + len(club_words) - 1]
                remaining.append({'text': tail, 'x0': last['x0'], 'x1': last['x1']})
            i += len(club_words)
            continue
        remaining.append(words[i])
        i += 1
    return remaining


def _split_name(name_words, name_order):
    """ Take in the words left over after club/position/salary are removed, return (first_name, last_name).

    Last name and first name sit in separate table columns, so the widest
    horizontal gap between adjacent words is the column break -- that survives
    multi-word names like 'Gomez Andrade' where a token count would not.
    """
    if not name_words:
        return None, None
    if len(name_words) == 1:  # Mononyms (Kaku, Robinho, Artur) print in a single cell
        return None, name_words[0]['text']

    gaps = [(name_words[i + 1]['x0'] - name_words[i]['x1'], i) for i in range(len(name_words) - 1)]
    _, split_at = max(gaps)
    left = ' '.join(w['text'] for w in name_words[:split_at + 1])
    right = ' '.join(w['text'] for w in name_words[split_at + 1:])

    return (right, left) if name_order == 'last_first' else (left, right)


def read_mlspa_salary_pdf(content, club_names, name_order, verbose=1):
    """ Take in PDF bytes, the known club names, and the release's name order, return a DataFrame.

    Rather than pin column x-positions per release (which shift year to year), each
    line is read semantically: every player row holds exactly two currency amounts,
    one club drawn from a known list, and at most one position code. Whatever
    survives that subtraction is the player's name.
    """
    # Longest first so 'Orlando City SC' wins over 'Orlando City'
    clubs_by_length = sorted(club_names, key=len, reverse=True)
    club_patterns = [
        (club, re.compile(r'(?<![A-Za-z])' + re.escape(club) + r'(?![a-z])'))
        for club in clubs_by_length
    ]

    rows = []
    skipped = []
    with pdfplumber.open(io.BytesIO(content)) as pdf:
        for page in pdf.pages:
            # Group words into lines by their vertical position. Reading words in the
            # PDF's own content-stream order keeps neighbouring cells apart: the 2022
            # release sets its club and last-name columns so tightly that sorting by
            # x-position alone interleaves them ('Minnesota UniteAdmarilla').
            lines = defaultdict(list)
            for word in page.extract_words(use_text_flow=True):
                lines[round(word['top'] / 2)].append(word)

            for key in sorted(lines):
                # The leftovers stay in stream order rather than sorted by x-position:
                # columns can physically overlap ('Sporting Kansas City' runs under the
                # last name 'Davis'), and sorting by x0 interleaves one cell into the next.
                amounts, remainder = _extract_amounts(lines[key])
                line_text = ' '.join(w['text'] for w in remainder)

                if len(amounts) != 2:
                    # Titles, column headers and page furniture land here
                    if amounts: skipped.append(line_text)
                    continue

                club = next((c for c, pattern in club_patterns if pattern.search(line_text)), None)
                if club is None:
                    skipped.append(line_text)
                    continue

                remainder = _strip_club(remainder, club)

                position = None
                name_words = []
                for word in remainder:
                    if position is None and POSITION_CODE.match(word['text']):
                        position = word['text']
                    else:
                        name_words.append(word)

                first_name, last_name = _split_name(name_words, name_order)
                if not last_name:
                    skipped.append(line_text)
                    continue

                rows.append({
                    'first_name': first_name,
                    'last_name': last_name,
                    'club': club,
                    'position': position,
                    'base_salary': amounts[0],
                    'guaranteed_comp': amounts[1],
                })

    if verbose >= 1 and skipped:
        print(f"Skipped {len(skipped)} non-player line(s) while parsing PDF")
    if verbose >= 2:
        for line in skipped: print(f"  skipped: {line}")

    return DataFrame(rows)


def get_MLSPA_mls_player_salaries(season, release, club_names, verbose=1):
    '''
    This function accepts a season, that season's release entry from data_vars.json,
    and the MLSPA club names to expect, downloads the release, and returns a
    DataFrame representation with string (or None) values.
    '''
    if verbose >= 2: print("Hello World from get_MLSPA_mls_player_salaries()")

    content = download_mlspa_release(release['url'], verbose=verbose)

    if release['format'] == 'csv':
        salaries_df = read_mlspa_salary_csv(content, release['column_map'], verbose=verbose)
    elif release['format'] == 'pdf':
        salaries_df = read_mlspa_salary_pdf(content, club_names, release['name_order'], verbose=verbose)
    else:
        raise ValueError(f"Unsupported MLSPA release format '{release['format']}' for season {season}")

    if salaries_df.empty:
        raise ValueError(f"No salary rows parsed from {release['url']}")

    # Trailing whitespace appears in club names and headers across releases
    for column in salaries_df.columns:
        salaries_df[column] = salaries_df[column].map(lambda v: v.strip() if isinstance(v, str) else v)

    salaries_df.insert(0, 'season', season)
    salaries_df['release_label'] = release['release_label']
    salaries_df['source_url'] = release['url']
    # Holding off on datatype changes bc of None values will err, all values passed as strings
    salaries_df = salaries_df.reindex(columns=MLSPA_COLUMNS)

    ##########  ##########  ##########
    if verbose >= 1: print(salaries_df.head(), "\n#####\n", salaries_df.tail())
    if verbose >= 2:
        with option_context('display.max_rows', None, 'display.max_columns', None):
            print(salaries_df)
    ##########  ##########  ##########

    return salaries_df
