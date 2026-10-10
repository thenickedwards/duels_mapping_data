import json
import os
import sqlite3

from data_handler import DataHandler, data_vars_path as default_data_vars_path
from dependencies.get_from_mlspa import get_MLSPA_mls_player_salaries
from dependencies.match_players import match_players_to_salaries

# Columns the salary pipeline adds to the Schmetzer Score tables, matching the
# definitions in etl/sql/create/schmetzer_scores_all.sql
SALARY_COLUMNS = [
    ('base_salary', 'REAL'),
    ('guaranteed_comp', 'REAL'),
    ('salary_match_tier', 'TEXT'),
    ('schmetzer_value_rk', 'INTEGER'),
]


class DH_MLSPA(DataHandler):
    """ ETL orchestration for the MLSPA salary guide.

    Salaries arrive one release per season from https://mlsplayers.org/resources/salary-guide
    and land in raw_MLSPA_mls_players_salaries, are typed and crosswalked to FBref club
    spellings in stg_MLSPA_mls_players_salaries, are matched by name to the players
    already scored there, and finally decorate schmetzer_scores_YYYY with what each
    club paid for the contested possession it got.

    This pipeline reads schmetzer_scores_YYYY, so it runs after the FBref pipeline
    has built those tables for the seasons in question.
    """

    def __init__(self, data_vars_path=None, mlspa_path=None):
        if data_vars_path is None:
            super().__init__()
            data_vars_path = default_data_vars_path
        else:
            super().__init__(data_vars_path)

        # The MLSPA releases are too source-specific to share data_vars.json, so they
        # have a file of their own beside it, defaulting to that sibling.
        if mlspa_path is None:
            mlspa_path = os.path.join(os.path.dirname(data_vars_path), "dv_mlspa.json")
        with open(mlspa_path, 'r', encoding='utf-8') as f:
            self.mlspa = json.load(f)
        self.salary_releases = self.mlspa["salary_releases"]

    def get_salary_seasons(self):
        """ Return the seasons dv_mlspa.json has an MLSPA release configured for. """
        return sorted(int(season) for season in self.salary_releases)

    ##### Setup #####

    def create_salary_tables(self):
        """ Create just the tables this pipeline owns, leaving the FBref tables alone. """
        for table_name in (self.club_crosswalk_table, self.salary_raw_table, self.salary_stg_table):
            self.create_table(table_name)

    def add_salary_columns_to_schmetzer_scores(self):
        """ Add the salary columns to Schmetzer Score tables that predate them.

        A database built before salaries existed already holds seasons of FBref data
        that can no longer be re-sourced, so the columns are added in place rather
        than by rebuilding the tables. Idempotent: on a freshly created database the
        columns are already there and nothing happens.
        """
        conn = self.connect()
        c = conn.cursor()
        try:
            tables = [self.schmetzer_scores_tables["all"]] + [
                f'schmetzer_scores_{season}' for season in self.get_schmetzer_season_tables(c)]
            for table in tables:
                c.execute(f'PRAGMA table_info("{table}")')
                existing = {row[1] for row in c.fetchall()}
                for column, column_type in SALARY_COLUMNS:
                    if column in existing:
                        continue
                    c.execute(f'ALTER TABLE "{table}" ADD COLUMN {column} {column_type}')
                    print(f'Added column: {table}.{column}')
            conn.commit()
        except sqlite3.Error as e:
            print(e)
        finally:
            conn.close()

    def drop_retired_salary_columns(self):
        """ Drop schmetzer_score_per_million from Schmetzer Score tables that still have it.

        The per-dollar figure is derived in the app from the score and salary columns,
        so it is no longer stored (October 2026). The season tables lose it whenever they
        are rescored; this clears it from schmetzer_scores_all, which is never rebuilt.
        Idempotent.
        """
        conn = self.connect()
        c = conn.cursor()
        try:
            c.execute('DROP INDEX IF EXISTS idx_schmetzer_scores_all__value')
            tables = [self.schmetzer_scores_tables["all"]] + [
                f'schmetzer_scores_{season}' for season in self.get_schmetzer_season_tables(c)]
            for table in tables:
                c.execute(f'PRAGMA table_info("{table}")')
                if 'schmetzer_score_per_million' in {row[1] for row in c.fetchall()}:
                    c.execute(f'ALTER TABLE "{table}" DROP COLUMN schmetzer_score_per_million')
                    print(f'Dropped column: {table}.schmetzer_score_per_million')
            conn.commit()
        except sqlite3.Error as e:
            print(e)
        finally:
            conn.close()

    ##### Extract, transform, load #####

    def _insert_raw_MLSPA_salaries_for_season(self, conn, cursor, season):
        """ Take in a connection, cursor and season, source that season's release into the raw table. """
        release = self.salary_releases[str(season)]
        # Only the MLSPA's own spellings are handed to the PDF parser. It finds the
        # club by looking for the longest known name in the line, so adding FBref's
        # short forms would let 'Austin' or 'LAFC' match inside a player's name.
        club_names = list(self.mlspa_club_aliases)
        df = get_MLSPA_mls_player_salaries(season=season, release=release, club_names=club_names)
        # Once new data obtained, remove existing data, then insert
        cursor.execute(f"DELETE FROM {self.salary_raw_table} WHERE season = ?", (season,))
        print(f'Deleted from table: {self.salary_raw_table} where season = {season}')
        conn.commit()
        df.to_sql(self.salary_raw_table, conn, if_exists='append', index=False)
        print(f'Inserted into table: {self.salary_raw_table} where season = {season}')
        conn.commit()

    def insert_historical_raw_MLSPA_mls_players_salaries(self):
        conn = self.connect()
        c = conn.cursor()
        ### Insert into raw table
        try:
            for season in self.get_salary_seasons():
                self._insert_raw_MLSPA_salaries_for_season(conn, c, season)
        except sqlite3.Error as e:
            print(e)
        finally:
            conn.close()

    def insert_current_raw_MLSPA_mls_players_salaries(self):
        conn = self.connect()
        c = conn.cursor()
        ### Insert into raw table
        try:
            seasons = self.get_salary_seasons()
            # The MLSPA publishes a spring release before the season ends, so the
            # newest configured release is the current one even part way through a year.
            season = self.current_year if self.current_year in seasons else max(seasons)
            self._insert_raw_MLSPA_salaries_for_season(conn, c, season)
        except sqlite3.Error as e:
            print(e)
        finally:
            conn.close()

    def insert_stg_MLSPA_mls_players_salaries(self, seasons=None):
        conn = self.connect()
        c = conn.cursor()
        try:
            sql_template = self.read_sql('transform', 'load_stg_MLSPA_mls_players_salaries.sql')
            for season in (seasons or self.get_salary_seasons()):
                c.executescript(sql_template.format(year=season))
                print(f'Inserted into table: {self.salary_stg_table} for season {season}')
                conn.commit()
        except sqlite3.Error as e:
            print(e)
        finally:
            conn.close()

    def match_stg_MLSPA_mls_players_salaries(self, seasons=None):
        """ Resolve each season's salary rows to the players scored in schmetzer_scores_YYYY.

        Neither source publishes an id the other shares, so the join is made on name
        within a club by dependencies/match_players.py and written back to staging as
        schmetzer_id plus the rule that produced it.
        """
        conn = self.connect()
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        try:
            scored_seasons = self.get_schmetzer_season_tables(c)
            for season in (seasons or self.get_salary_seasons()):
                if season not in scored_seasons:
                    print(f'Skipped matching salaries for season {season}: no schmetzer_scores_{season} table')
                    continue

                players = [dict(r) for r in c.execute(
                    f'SELECT id, player_name, squad FROM "schmetzer_scores_{season}"')]
                salaries = [dict(r) for r in c.execute(
                    f"SELECT salary_key AS key, player_first_name AS first_name, "
                    f"player_last_name AS last_name, squad "
                    f"FROM {self.salary_stg_table} WHERE season = ?", (season,))]

                print(f'Matching {len(salaries)} salary records to {len(players)} players for season {season}')
                matches, _ = match_players_to_salaries(players, salaries)

                c.execute(f"UPDATE {self.salary_stg_table} "
                          f"SET schmetzer_id = NULL, salary_match_tier = NULL WHERE season = ?", (season,))
                c.executemany(
                    f"UPDATE {self.salary_stg_table} "
                    f"SET schmetzer_id = :schmetzer_id, salary_match_tier = :match_tier "
                    f"WHERE salary_key = :salary_key",
                    [{'schmetzer_id': player_id, **match} for player_id, match in matches.items()])
                print(f'Updated table: {self.salary_stg_table} with {len(matches)} matches for season {season}')
                conn.commit()
        except sqlite3.Error as e:
            print(e)
        finally:
            conn.close()

    def update_schmetzer_scores_players_salaries(self, seasons=None):
        """ Apply matched salaries to each season's scores and derive the value metric. """
        conn = self.connect()
        c = conn.cursor()
        try:
            sql_template = self.read_sql('z_schmetzer_scores', 'update_schmetzer_scores_players_salaries.sql')
            scored_seasons = self.get_schmetzer_season_tables(c)
            for season in (seasons or self.get_salary_seasons()):
                if season not in scored_seasons:
                    continue
                c.executescript(sql_template.format(
                    year=season,
                    salary_basis=self.salary["value_metric_basis"],
                    min_nineties=self.salary["min_nineties_for_value_rank"],
                ))
                print(f'Updated table: schmetzer_scores_{season} with salaries and value metric')
                conn.commit()
        except sqlite3.Error as e:
            print(e)
        finally:
            conn.close()

    def report_salary_coverage(self):
        """ Print how many scored players carry a salary, by season, so gaps are visible. """
        conn = self.connect()
        c = conn.cursor()
        try:
            for season in self.get_schmetzer_season_tables(c):
                c.execute(f'SELECT COUNT(*), COUNT(guaranteed_comp) FROM "schmetzer_scores_{season}"')
                total, matched = c.fetchone()
                pct = (100.0 * matched / total) if total else 0.0
                print(f'  {season}: {matched}/{total} players with salary ({pct:.1f}%)')
        except sqlite3.Error as e:
            print(e)
        finally:
            conn.close()
