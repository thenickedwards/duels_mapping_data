import json
import os
import sqlite3
from collections import defaultdict

from data_handler import DataHandler, data_vars_path as default_data_vars_path
from dependencies.get_from_whoscored import (
    PROFILE_POSITION_GROUPS,
    get_WhoScored_mls_player_match_stats,
    get_WhoScored_mls_schedule,
    get_WhoScored_player_profile,
    get_WhoScored_reader,
)
from dependencies.match_players import name_tokens, normalize_player_name


class DH_WhoScored(DataHandler):
    """ ETL orchestration for the WhoScored match feed, which replaces FBref from 2026.

    FBref's Player Miscellaneous Stats table was a season sum of Opta events. Opta cut
    Sports Reference off in January 2026, and FBref now turns scrapers away, so the same
    events are read from WhoScored's match pages instead. Each finished match lands in
    raw_WhoScored_mls_players_match_stats as one row per player; players are resolved to
    the identity the app already knows them by in dim_WhoScored_mls_players; and each
    season is summed into stg_WhoScored_mls_players_all_stats_misc, which has the FBref
    staging table's shape. The Schmetzer Score scripts read both through the
    stg_mls_players_all_stats_misc view.

    Run by hand only. Every page fetched is cached (see cache_dir in dv_whoscored.json),
    so a re-run fetches only matches played since the last one.
    """

    def __init__(self, data_vars_path=None, whoscored_path=None):
        if data_vars_path is None:
            super().__init__()
            data_vars_path = default_data_vars_path
        else:
            super().__init__(data_vars_path)

        # WhoScored's settings are source-specific, so they have a file of their own
        # beside data_vars.json, defaulting to that sibling.
        if whoscored_path is None:
            whoscored_path = os.path.join(os.path.dirname(data_vars_path), "dv_whoscored.json")
        with open(whoscored_path, 'r', encoding='utf-8') as f:
            whoscored = json.load(f)
            self.whoscored_league = whoscored["league"]
            self.whoscored_first_season = whoscored["first_season"]
            self.whoscored_regular_season_only = whoscored["regular_season_only"]
            self.whoscored_cache_dir = whoscored["cache_dir"]
            self.whoscored_headless = whoscored["headless"]
            self.nationality_iso_to_fifa = whoscored["nationality_iso_to_fifa"]

        with open(data_vars_path, 'r') as f:
            database = json.load(f)["database"]
            self.whoscored_raw_table = database["whoscored_raw_table"]
            self.whoscored_profiles_table = database["whoscored_profiles_table"]
            self.whoscored_players_table = database["whoscored_players_table"]
            self.whoscored_stg_table = database["whoscored_stg_table"]

        self._readers = {}

    def get_whoscored_seasons(self):
        """ Return the seasons WhoScored is the source for: the first one through the current year. """
        return list(range(self.whoscored_first_season, self.current_year + 1))

    def get_reader(self, season):
        """ Take in a season, return a WhoScored reader for it, starting the browser only once. """
        if season not in self._readers:
            self._readers[season] = get_WhoScored_reader(
                self.whoscored_league, season, self.whoscored_cache_dir, self.whoscored_headless)
        return self._readers[season]

    ##### Setup #####

    def create_whoscored_tables(self):
        """ Create just the tables this pipeline owns, plus the staging view that reads them.

        Leaves the FBref tables alone -- they can no longer be re-sourced. The crosswalk
        is created only if missing, since the salary pipeline shares it.
        """
        for table_name in (self.whoscored_raw_table, self.whoscored_profiles_table,
                           self.whoscored_players_table, self.whoscored_stg_table, self.stg_view):
            self.create_table(table_name)

        conn = self.connect()
        c = conn.cursor()
        try:
            c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name = ?",
                      (self.club_crosswalk_table,))
            crosswalk_exists = c.fetchone() is not None
        finally:
            conn.close()
        if not crosswalk_exists:
            self.create_table(self.club_crosswalk_table)

    ##### Extract #####

    def _insert_raw_WhoScored_for_season(self, conn, cursor, season):
        """ Take in a connection, cursor and season, source that season's finished matches into the raw table. """
        reader = self.get_reader(season)
        games = get_WhoScored_mls_schedule(reader, regular_season_only=self.whoscored_regular_season_only)
        df = get_WhoScored_mls_player_match_stats(reader, self.whoscored_league["key"], games)
        # Once new data obtained, remove existing data, then insert
        cursor.execute(f"DELETE FROM {self.whoscored_raw_table} WHERE season = ?", (season,))
        print(f'Deleted from table: {self.whoscored_raw_table} where season = {season}')
        conn.commit()
        df.to_sql(self.whoscored_raw_table, conn, if_exists='append', index=False)
        print(f'Inserted into table: {self.whoscored_raw_table} where season = {season} '
              f'({len(df)} player-match rows from {df["game_id"].nunique()} games)')
        conn.commit()

    def insert_historical_raw_WhoScored_mls_players_match_stats(self):
        conn = self.connect()
        c = conn.cursor()
        ### Insert into raw table
        try:
            for season in self.get_whoscored_seasons():
                self._insert_raw_WhoScored_for_season(conn, c, season)
        except sqlite3.Error as e:
            print(e)
        finally:
            conn.close()

    def insert_current_raw_WhoScored_mls_players_match_stats(self):
        conn = self.connect()
        c = conn.cursor()
        ### Insert into raw table
        try:
            self._insert_raw_WhoScored_for_season(conn, c, self.current_year)
        except sqlite3.Error as e:
            print(e)
        finally:
            conn.close()

    ##### Transform #####

    def _get_fbref_identities(self, cursor):
        """ Take in a cursor, return each FBref player's latest record indexed by name.

        One record per (name, birth year), from the latest season they appear in, so a
        player is aged forward from the most recent thing FBref knew about them. Keyed by
        the normalized name with its spaces removed, so 'Jeong Sangbin' and WhoScored's
        'Jeong Sang-Bin' share a key.
        """
        cursor.execute(f"""
            SELECT player_name, player_nationality, player_yob, player_age, season, position
            FROM {self.stg_table} stg
            WHERE season = (SELECT MAX(season) FROM {self.stg_table} latest
                            WHERE latest.player_name = stg.player_name
                              AND latest.player_yob IS stg.player_yob)
        """)
        by_name = defaultdict(list)
        seen = set()
        for name, nationality, yob, age, season, position in cursor.fetchall():
            if (name, yob) in seen:
                continue  # traded players have a row per squad in their last season
            seen.add((name, yob))
            by_name[self._name_key(name)].append({
                'normalized_name': normalize_player_name(name),
                'player_name': name, 'player_nationality': nationality, 'player_yob': yob,
                'fbref_age': age, 'fbref_season': season,
                'fallback_position': position.split(',')[0] if position else None,
            })
        return by_name

    @staticmethod
    def _name_key(name):
        """ Take in a player name, return it normalized with the spaces removed. """
        return normalize_player_name(name).replace(' ', '')

    def _match_fbref_by_name(self, fbref_by_name, whoscored_name, fetched_age, fetched_year):
        """ Take in a WhoScored name and age, return the one FBref identity it matches, or None.

        The name must match once normalized, and the birth year must agree with the age
        WhoScored showed when its page was fetched -- two footballers can share a name.
        """
        candidates = fbref_by_name.get(self._name_key(whoscored_name), [])
        if fetched_age is not None:
            # Born fetched_year - age, or a year earlier if the birthday had not come yet;
            # one more year of slack covers a page cached across a birthday
            plausible = range(fetched_year - fetched_age - 2, fetched_year - fetched_age + 1)
            candidates = [c for c in candidates if c['player_yob'] in plausible]
        return candidates[0] if len(candidates) == 1 else None

    def _match_fbref_by_profile(self, fbref_by_name, whoscored_name, yob):
        """ Take in a WhoScored name and birth year, return the one FBref identity it matches, or None.

        For names the sources spell differently ('Danny' and 'Daniel Musovski'): same
        birth year, same surname, and first names starting with the same letter.
        """
        tokens = name_tokens(normalize_player_name(whoscored_name))
        if yob is None or not tokens:
            return None
        matches = []
        for candidates in fbref_by_name.values():
            for candidate in candidates:
                fbref_tokens = name_tokens(candidate['normalized_name'])
                if (fbref_tokens and candidate['player_yob'] == yob
                        and fbref_tokens[-1] == tokens[-1] and fbref_tokens[0][0] == tokens[0][0]):
                    matches.append(candidate)
        return matches[0] if len(matches) == 1 else None

    @staticmethod
    def _identity(fbref):
        """ Take in an FBref candidate, return just the fields dim_WhoScored_mls_players stores. """
        return {k: v for k, v in fbref.items() if k != 'normalized_name'}

    def insert_dim_WhoScored_mls_players(self, seasons=None, fetch_profiles=True):
        """ Resolve each new WhoScored player id to a name, nationality and birth year.

        A player FBref already knew keeps FBref's name, nationality and birth year, so
        their history stays joined up in the app; anyone else is read from their
        WhoScored profile page (one fetch per player, cached). Players already resolved
        are skipped, so each run only does the newcomers. Pass fetch_profiles=False to
        skip the profile fetches and leave newcomers with WhoScored's name alone; they
        stay unresolved (detail_source NULL) and are tried again on the next run.
        """
        conn = self.connect()
        c = conn.cursor()
        try:
            fbref_by_name = self._get_fbref_identities(c)
            for season in (seasons or self.get_whoscored_seasons()):
                c.execute(f"""
                    SELECT raw.player_id, MAX(raw.player), MAX(raw.age), MAX(raw.load_datetime)
                    FROM {self.whoscored_raw_table} raw
                    WHERE raw.season = ?
                      AND raw.player_id NOT IN (SELECT player_id FROM {self.whoscored_players_table}
                                                WHERE detail_source IS NOT NULL)
                    GROUP BY raw.player_id
                """, (season,))
                newcomers = c.fetchall()
                print(f'Resolving {len(newcomers)} new players for season {season}')

                tally = defaultdict(int)
                for i, (player_id, whoscored_name, fetched_age, loaded) in enumerate(newcomers, start=1):
                    fetched_year = int(loaded[:4]) if loaded else self.current_year
                    row = {'player_id': player_id, 'whoscored_name': whoscored_name,
                           'player_name': whoscored_name, 'player_nationality': None,
                           'player_yob': None, 'birth_date': None, 'fbref_season': None,
                           'fbref_age': None, 'fallback_position': None, 'detail_source': None}

                    fbref = self._match_fbref_by_name(fbref_by_name, whoscored_name, fetched_age, fetched_year)
                    if fbref:
                        row.update(self._identity(fbref), detail_source='fbref_name')
                    elif fetch_profiles:
                        print(f'  [{i}/{len(newcomers)}] Sourcing profile for {whoscored_name} ({player_id})')
                        profile = self._get_profile(c, season, player_id)
                        yob = int(profile['birth_date'][:4]) if profile.get('birth_date') else None
                        row.update(
                            player_nationality=self.nationality_iso_to_fifa.get(profile.get('nationality_iso') or ''),
                            player_yob=yob,
                            birth_date=profile.get('birth_date'),
                            fallback_position=self._profile_position(profile.get('positions')),
                            detail_source='whoscored_profile')
                        fbref = self._match_fbref_by_profile(fbref_by_name, whoscored_name, yob)
                        if fbref:
                            # Keep the profile's exact birth date but FBref's spelling and
                            # nationality, so the player's FBref seasons join up
                            identity = self._identity(fbref)
                            identity.pop('fallback_position')
                            row.update(identity, detail_source='fbref_profile')
                            row['fallback_position'] = row['fallback_position'] or fbref['fallback_position']
                        elif not profile:
                            row['detail_source'] = None  # try again next run

                    tally[row['detail_source']] += 1
                    c.execute(f"""
                        INSERT OR REPLACE INTO {self.whoscored_players_table}
                            (player_id, whoscored_name, player_name, player_nationality, player_yob,
                             birth_date, fbref_season, fbref_age, fallback_position, detail_source)
                        VALUES (:player_id, :whoscored_name, :player_name, :player_nationality, :player_yob,
                                :birth_date, :fbref_season, :fbref_age, :fallback_position, :detail_source)
                    """, row)
                    conn.commit()
                print(f'Inserted into table: {self.whoscored_players_table} for season {season}: '
                      + ', '.join(f'{source or "unresolved"} {n}' for source, n in sorted(tally.items(), key=str)))
        except sqlite3.Error as e:
            print(e)
        finally:
            conn.close()

    def _get_profile(self, cursor, season, player_id):
        """ Take in a cursor, season and player id, return their profile, fetching it once ever. """
        cursor.execute(f"SELECT player, nationality, nationality_iso, birth_date, positions "
                       f"FROM {self.whoscored_profiles_table} WHERE player_id = ?", (player_id,))
        stored = cursor.fetchone()
        if stored:
            return dict(zip(('player', 'nationality', 'nationality_iso', 'birth_date', 'positions'), stored))
        try:
            profile = get_WhoScored_player_profile(self.get_reader(season), player_id)
        except Exception as e:  # A missing profile should not stop the run
            print(f'  ⚠️  Could not source profile for player {player_id}: {e}')
            return {}
        cursor.execute(f"""
            INSERT OR REPLACE INTO {self.whoscored_profiles_table}
                (player_id, player, nationality, nationality_iso, birth_date, positions)
            VALUES (:player_id, :player, :nationality, :nationality_iso, :birth_date, :positions)
        """, profile)
        if profile.get('nationality_iso') and profile['nationality_iso'] not in self.nationality_iso_to_fifa:
            print(f"  ⚠️  No FIFA code for nationality '{profile.get('nationality')}' "
                  f"({profile['nationality_iso']}); add it to nationality_iso_to_fifa in dv_whoscored.json")
        return profile

    @staticmethod
    def _profile_position(positions):
        """ Take in a profile's Positions line, return its first as GK/DF/MF/FW. """
        for word in (positions or '').replace(',', ' ').split():
            if word in PROFILE_POSITION_GROUPS:
                return PROFILE_POSITION_GROUPS[word]
        return None

    def insert_stg_WhoScored_mls_players_all_stats_misc(self, seasons=None):
        conn = self.connect()
        c = conn.cursor()
        try:
            sql_template = self.read_sql('transform', 'load_stg_WhoScored_mls_players_all_stats_misc.sql')
            for season in (seasons or self.get_whoscored_seasons()):
                c.executescript(sql_template.format(year=season))
                print(f'Inserted into table: {self.whoscored_stg_table} for season {season}')
                conn.commit()
        except sqlite3.Error as e:
            print(e)
        finally:
            conn.close()

    ##### Reports #####

    def report_whoscored_coverage(self, seasons=None):
        """ Print what each season's staging rows are missing, so gaps are visible before a sync.

        Flags squads the crosswalk did not recognise (add them to whoscored_squad_aliases
        in dv_clubs_cw.json) and players left without a nationality or birth year.
        """
        conn = self.connect()
        c = conn.cursor()
        try:
            canonical = set(self.mls_squad_names)
            for season in (seasons or self.get_whoscored_seasons()):
                c.execute(f"SELECT COUNT(*), COUNT(player_nationality), COUNT(player_yob) "
                          f"FROM {self.whoscored_stg_table} WHERE season = ?", (season,))
                total, nationality, yob = c.fetchone()
                print(f'  {season}: {total} rows, {nationality} with nationality, {yob} with birth year')
                c.execute(f"SELECT DISTINCT squad FROM {self.whoscored_stg_table} WHERE season = ?", (season,))
                unknown = sorted(s for (s,) in c.fetchall() if s not in canonical)
                if unknown:
                    print(f'  ⚠️  {season}: squads missing from the crosswalk: {unknown}')
        except sqlite3.Error as e:
            print(e)
        finally:
            conn.close()
