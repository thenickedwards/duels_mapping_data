import json
import glob
import os
import datetime
import sqlite3
from dotenv import load_dotenv
from supabase import create_client, Client
from supafunc.errors import FunctionsRelayError, FunctionsHttpError
from dependencies.connect_db import connect_db
from dependencies.get_from_fbref import get_FBref_mls_player_misc_stats
from dependencies.normalize_data import find_none, normalize_none_to_null, normalize_row

# Credentials are read from .env by resolve_supabase_write_credentials(). Loading here
# too keeps DataHandler usable when imported directly, not only via a pipeline script.
load_dotenv()

script_dir = os.path.dirname(os.path.abspath(__file__))
data_vars_path = os.path.join(script_dir, "..", "data_vars.json")
data_vars_path = os.path.normpath(data_vars_path)
sql_dir = os.path.join(script_dir, "sql")

class DataHandler:
    """ Base ETL orchestration class.

    Everything every pipeline needs -- the data_vars configuration, the database
    connection, running a SQL script, listing the season tables, and the upload to
    Supabase -- lives here. Anything specific to one source belongs in a subclass
    named for that source and prefixed DH_ (see DH_MLSPA in dh_mlspa_salaries.py), so
    a new pipeline is a new subclass rather than another method on this class.
    """
    def __init__(self, data_vars_path=data_vars_path, clubs_cw_path=None):
        with open(data_vars_path, 'r') as f:
            data_vars = json.load(f)
            self.database_name = data_vars["database"]["name"]
            self.database_path = data_vars["database"]["path"] + data_vars["database"]["name"]
            # base_dir = os.path.dirname(os.path.abspath(data_vars_path))
            # full_path = os.path.join(base_dir, data_vars["database"]["path"], self.database_name)
            # self.database_path = os.path.normpath(full_path)
            # print(f"📂 Database will be opened from: {self.database_path}")
            self.inaugural_season = data_vars["database"]["inaugural_season"]
            self.current_year = datetime.datetime.now().year
            self.raw_table = data_vars["database"]["misc_raw_table"]
            self.stg_table = data_vars["database"]["misc_stg_table"]
            self.stg_view = data_vars["database"]["misc_stg_view"]
            self.misc_season_current  = data_vars["fbref"]["fbref_urls"]["misc_season_current"]
            self.misc_season_specific  = data_vars["fbref"]["fbref_urls"]["misc_season_specific"]
            self.schmetzer_score = data_vars["schmetzer_score_points"]
            self.schmetzer_scores_tables = data_vars["database"]["schmetzer_scores_tables"] 
            self.salary_raw_table = data_vars["database"]["salary_raw_table"]
            self.salary_stg_table = data_vars["database"]["salary_stg_table"]
            self.club_crosswalk_table = data_vars["database"]["club_crosswalk_table"]
            self.schmetzer_points_table = data_vars["database"]["schmetzer_points_table"]
            self.salary = data_vars["salary"]

        # The club crosswalk is reference data rather than configuration, so it has a
        # file of its own beside data_vars.json. Defaults to that sibling so a custom
        # data_vars_path keeps its own crosswalk.
        if clubs_cw_path is None:
            clubs_cw_path = os.path.join(os.path.dirname(data_vars_path), "dv_clubs_cw.json")
        with open(clubs_cw_path, 'r', encoding='utf-8') as f:
            clubs_cw = json.load(f)
            self.mls_squad_names = clubs_cw["mls_squad_names"]
            self.fbref_squad_aliases = clubs_cw["fbref_squad_aliases"]
            self.mlspa_club_aliases = clubs_cw["mlspa_club_aliases"]
            self.whoscored_squad_aliases = clubs_cw["whoscored_squad_aliases"]

    ##### Shared plumbing available to every pipeline #####

    def connect(self):
        """ Return a connection to the SQLite database named in data_vars.json. """
        return connect_db(self.database_name, self.database_path)

    def read_sql(self, *path_parts):
        """ Take in path parts below etl/sql/, return the contents of that SQL file. """
        with open(os.path.join(sql_dir, *path_parts), 'r') as f:
            return f.read()

    def create_table(self, table_name):
        """ Take in a table name, run the matching script from etl/sql/create/.

        create_tables() rebuilds the whole environment and drops every table with it.
        This runs a single CREATE script instead, so a pipeline can stand up its own
        tables without disturbing tables it does not own.
        """
        conn = self.connect()
        c = conn.cursor()
        try:
            c.executescript(self.read_sql('create', f'{table_name}.sql'))
            print(f'Created table: {table_name}')
            conn.commit()
        except sqlite3.Error as e:
            print(e)
        finally:
            conn.close()

    def insert_dim_mls_club_crosswalk(self):
        """ Load every source's club spellings into the crosswalk.

        There is one crosswalk table and one canonical set of squad names, and every
        feed resolves against it so a club reads identically wherever it came from.
        It lives on the base because every pipeline refreshes it.
        """
        conn = self.connect()
        c = conn.cursor()
        try:
            c.execute(f"DELETE FROM {self.club_crosswalk_table}")
            for source, aliases in (('fbref', self.fbref_squad_aliases),
                                    ('mlspa', self.mlspa_club_aliases),
                                    ('whoscored', self.whoscored_squad_aliases)):
                for club_alias, squad in aliases.items():
                    c.execute(
                        f"INSERT OR REPLACE INTO {self.club_crosswalk_table} "
                        f"VALUES (:club_alias, :source, :squad)",
                        {'club_alias': club_alias, 'source': source, 'squad': squad})
                print(f'Inserted into table: {self.club_crosswalk_table} '
                      f'{len(aliases)} {source} club spellings')
            conn.commit()
        except sqlite3.Error as e:
            print(e)
        finally:
            conn.close()

    def standardize_squad_names(self):
        """ Apply the club crosswalk to tables built before squad names were standardized.

        Both staging loads standardize going forward. This corrects a database that
        already holds the raw source spellings, in place rather than by rebuilding --
        the FBref raw and staging tables can no longer be re-sourced. Idempotent.

        Note the Schmetzer Score ids change with the squad slug they embed, so anything
        holding a reference to them (Supabase rows, stg salary matches) needs refreshing
        afterwards. See the README.
        """
        conn = self.connect()
        c = conn.cursor()
        try:
            c.executescript(self.read_sql('migrate', 'standardize_squad_names_stg.sql'))
            print(f'Standardized squad names in table: {self.stg_table}')
            conn.commit()

            sql_template = self.read_sql('migrate', 'standardize_squad_names_scores.sql')
            tables = [f'schmetzer_scores_{season}' for season in self.get_schmetzer_season_tables(c)]
            tables.append(self.schmetzer_scores_tables["all"])
            for table in tables:
                c.executescript(sql_template.format(table=table))
                print(f'Standardized squad names in table: {table}')
                conn.commit()
        except sqlite3.Error as e:
            print(e)
        finally:
            conn.close()

    def report_squad_names(self):
        """ Print the distinct squad names now in the Schmetzer Score tables. """
        conn = self.connect()
        c = conn.cursor()
        try:
            c.execute(f'SELECT squad, COUNT(*) FROM {self.schmetzer_scores_tables["all"]} '
                      f'GROUP BY squad ORDER BY squad')
            for squad, count in c.fetchall():
                print(f'  {squad} ({count})')
        except sqlite3.Error as e:
            print(e)
        finally:
            conn.close()

    def get_schmetzer_season_tables(self, cursor):
        """ Take in a cursor, return the seasons that already have a schmetzer_scores_YYYY table. """
        cursor.execute("""
            SELECT name FROM sqlite_master
            WHERE type='table' AND name LIKE 'schmetzer_scores_20__'
            ORDER BY name;
        """)
        return [int(row[0][-4:]) for row in cursor.fetchall() if row[0][-4:].isdigit()]

    def create_tables(self):
        conn = connect_db(self.database_name, self.database_path)
        c = conn.cursor()
        try:
            for sql_file in glob.glob('app-duels-mapping/public/duels_mapping_data/etl/sql/create/*.sql'):
                with open(sql_file, 'r') as f:
                    table_name = os.path.splitext(os.path.basename(sql_file))[0]
                    sql = f.read()
                    c.executescript(sql)
                    print(f'Created table: {table_name}')
                    conn.commit()
        except sqlite3.Error as e:
            print(e)
        finally:
            conn.close()
            
    def insert_dim_schmetzer_score_points(self):
        """ Load the weights from data_vars.json into the dim table.

        Upserts on stat_name rather than plain INSERT, so retuning the weights is a
        config edit plus this method -- the original INSERT could only run against a
        table create_tables() had just dropped, and create_tables() also drops the
        FBref tables, which can no longer be re-sourced.
        """
        conn = connect_db(self.database_name, self.database_path)
        c = conn.cursor()
        try:
            for stat_name, stat_info in self.schmetzer_score.items():
                point_value = stat_info["point_value"]
                abbrev = stat_info["abbrev"]
                c.execute("INSERT INTO dim_schmetzer_score_points VALUES (:stat_name, :point_value, :abbrev) "
                          "ON CONFLICT(stat_name) DO UPDATE SET point_value = excluded.point_value, abbrev = excluded.abbrev",
                          {'stat_name': stat_name, 'point_value': point_value, 'abbrev': abbrev})
                conn.commit()
                print(f'Inserted into table: dim_schmetzer_score_points {stat_name} with point_value: {point_value} and abbrev: {abbrev}')
        except sqlite3.Error as e:
            print(e)
        finally:
            conn.close()
        
    def insert_historical_raw_FBref_mls_players_all_stats_misc(self):
        conn = connect_db(self.database_name, self.database_path)
        c = conn.cursor()
        ### Insert into raw table
        try:
            for year in range(2018, self.current_year):
                url = f'https://FBref.com/en/comps/22/{year}/misc/{year}-Major-League-Soccer-Stats'
                df = get_FBref_mls_player_misc_stats(year=year, url=url)
                # Once new data obtained, remove existing data, then insert
                c.execute(f"DELETE FROM {self.raw_table} WHERE season = ?", (year,))
                print(f'Deleted from table: {self.raw_table} where season = {year}')
                conn.commit()
                df.to_sql(self.raw_table, conn, if_exists='append', index=False)
                print(f'Inserted into table: {self.raw_table} where season = {year}')
                conn.commit()
        except sqlite3.Error as e:
            print(e)
        finally:
            conn.close()
        
    def insert_current_raw_FBref_mls_players_all_stats_misc(self):
        conn = connect_db(self.database_name, self.database_path)
        c = conn.cursor()
        ### Insert into raw table
        try:
            url = self.misc_season_current
            df = get_FBref_mls_player_misc_stats(year=self.current_year, url=url)
            # Once new data obtained, remove existing data, then insert
            c.execute(f"DELETE FROM {self.raw_table} WHERE season = ?", (self.current_year,))
            print(f'Deleted from table: {self.raw_table} where season = {self.current_year}')
            conn.commit()
            df.to_sql(self.raw_table, conn, if_exists='append', index=False)
            print(f'Inserted into table: {self.raw_table} where season = {self.current_year}')
            conn.commit()
        except sqlite3.Error as e:
            print(e)
        finally:
            conn.close()
    
    def insert_stg_FBref_mls_players_all_stats_misc(self):
        conn = connect_db(self.database_name, self.database_path)
        c = conn.cursor()
        try:
            sql_file = glob.glob('app-duels-mapping/public/duels_mapping_data/etl/sql/transform/load_stg_FBref_mls_players_all_stats_misc.sql')[0]
            with open(sql_file, 'r') as f:
                table_name = os.path.splitext(os.path.basename(sql_file))[0].replace('load_', '')
                sql = f.read()
                c.executescript(sql)
                print(f'Inserted into table: {table_name}')
                conn.commit()
        except sqlite3.Error as e:
            print(e)
        finally:
            conn.close()
    
    def refresh_stg_FBref_mls_players_all_stats_misc(self, season):
        """ Rebuild one season of FBref staging from the raw table.

        insert_stg_FBref_mls_players_all_stats_misc() only adds players staging has not
        seen, so a season reloaded into raw never updates the totals already staged.
        This replaces the season outright. Offline and safe to re-run: it reads the raw
        table, which is left untouched.
        """
        conn = self.connect()
        c = conn.cursor()
        try:
            c.executescript(self.read_sql('migrate', 'refresh_stg_FBref_mls_players_all_stats_misc.sql').format(year=season))
            print(f'Refreshed table: {self.stg_table} for season {season} from table: {self.raw_table}')
            conn.commit()
        except sqlite3.Error as e:
            print(e)
        finally:
            conn.close()

    def insert_schmetzer_scores_players(self, seasons=None):
        """ Score and rank each season from the staging view.

        The view (stg_mls_players_all_stats_misc) reads FBref for 2018-2025 and
        WhoScored from 2026, so each season scores the same way whatever its source.

        Defaults to every season from the inaugural one through the current year.
        Pass seasons to rescore only the ones already in the database -- retuning the
        weights has to rebuild these tables, and the default range would otherwise
        create an empty table for a season the dead FBref feed never delivered.
        """
        conn = connect_db(self.database_name, self.database_path)
        c = conn.cursor()
        try:
            sql_file = glob.glob('app-duels-mapping/public/duels_mapping_data/etl/sql/z_schmetzer_scores/schmetzer_scores_players.sql')[0]
            for year in (seasons or range(2018, self.current_year + 1)):
                with open(sql_file, 'r') as f:
                    table_name = f'schmetzer_scores_{year}'
                    sql = f.read()
                    sql = sql.format(year=year)
                    c.executescript(sql)
                    print(f'Created table: {table_name} and inserted player data from view: {self.stg_view} for season {year}')
                    conn.commit()
        except sqlite3.Error as e:
            print(e)
        finally:
            conn.close()
    
    def insert_schmetzer_scores_all_seasons(self):
        conn = connect_db(self.database_name, self.database_path)
        c = conn.cursor()
        try:
             # Find all schmetzer_scores_YYYY tables
            c.execute("""
                SELECT name FROM sqlite_master
                WHERE type='table' AND name LIKE 'schmetzer_scores_20__';
            """)
            schmetzer_season_tables = [row[0] for row in c.fetchall()]
            
            sql_file = glob.glob('app-duels-mapping/public/duels_mapping_data/etl/sql/z_schmetzer_scores/schmetzer_scores_all.sql')[0]
            with open(sql_file, 'r') as f:
                sql_template = f.read()

            for table in schmetzer_season_tables:
                year_match = table[-4:]
                if not year_match.isdigit():
                    continue
                year = int(year_match)

                sql = sql_template.format(year=year)
                c.executescript(sql)
                print(f'Inserted player data into schmetzer_scores_all from table: {table} for season {year}')
                conn.commit()
        except sqlite3.Error as e:
            print(e)
        finally:
            conn.close()
            
            
    # Columns a Schmetzer Score table ships to Supabase. The per-stat _pts columns are
    # deliberately absent: Supabase serves scores, it never recomputes them.
    SUPABASE_SCORE_COLUMNS = (
        "id, season, player_name, player_nationality, position, squad, player_age, "
        "player_yob, nineties, schmetzer_score, schmetzer_rk, aerial_duels_won, "
        "aerial_duels_lost, aerial_duels_total, aerial_duels_won_pct, tackles_won, "
        "interceptions, recoveries, base_salary, guaranteed_comp, salary_match_tier, "
        "schmetzer_value_rk"
    )
    SUPABASE_SCHMETZER_POINTS_COLUMNS = "stat_name, point_value, abbrev"

    def _upsert_table_to_supabase(self, supabase, cursor, table, columns, on_conflict,
                                  scored_rows_only=False):
        """ Take a SQLite table, upsert its rows into the Supabase table of the same name.

        scored_rows_only drops rows without an integer season, which the score tables
        can carry and Postgres rejects; dim tables have no season column at all.
        """
        print(f"Extracting data from SQLite table: {table}")
        cursor.execute(f"SELECT {columns} FROM {table}")
        rows = cursor.fetchall()
        if scored_rows_only:
            rows = [r for r in rows if r['season'] is not None and isinstance(r['season'], int)]
        data = [normalize_row(r) for r in rows]
        supabase.table(table).upsert(data, default_to_null=True, on_conflict=on_conflict).execute()
        print(f'Inserted data into Supbase table: {table} ({len(data)} rows)')

    def resolve_supabase_write_credentials(self):
        """ Return (url, key) for the sync, preferring the service role key.

        The anon key is public -- it ships to every browser that loads the deployed app --
        so a database the sync can write to with it is a database anyone can write to.
        The service role key bypasses RLS, which lets the Supabase tables be genuinely
        read-only to anon while this pipeline still writes.

        Falls back to the anon key with a warning rather than failing, so a checkout
        without SUPABASE_SERVICE_ROLE_KEY set keeps working against tables that still
        allow anon writes. Once the RLS lockdown migration has been applied, that
        fallback stops working, by design -- add the key to .env.
        """
        url = (os.getenv("SUPABASE_URL") or "").strip()
        service_key = (os.getenv("SUPABASE_SERVICE_ROLE_KEY") or "").strip()
        if service_key:
            return url, service_key

        print("⚠️  SUPABASE_SERVICE_ROLE_KEY is not set -- falling back to SUPABASE_ANON_KEY.")
        print("   The anon key is public, so this only works while the Supabase tables")
        print("   accept anon writes. See the README on restricting write access.")
        return url, (os.getenv("SUPABASE_ANON_KEY") or "").strip()

    def insert_SQLite_to_Supabase(self, supabase_url=None, supabase_key=None):
        """ Push the tables the app serves, plus the weights behind them, to Supabase.

        Credentials default to resolve_supabase_write_credentials(), so callers do not
        each decide which key the sync writes with.

        The score tables go first and the dim table last on purpose. dim_schmetzer_score_points
        is not read by the app -- it is carried so the cloud copy records which weights
        produced the scores sitting next to it -- so a Supabase side missing that table
        must not block the upload the app actually depends on. It needs creating once,
        via etl/sql/z_supabase/create_dim_schmetzer_score_points_supabase.sql.
        """
        # Supabase client
        if supabase_url is None or supabase_key is None:
            resolved_url, resolved_key = self.resolve_supabase_write_credentials()
            supabase_url = supabase_url or resolved_url
            supabase_key = supabase_key or resolved_key
        supabase: Client = create_client(supabase_url, supabase_key)
        # SQLite connection
        conn = connect_db(self.database_name, self.database_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        try:
            # Every season that has been scored, whichever source it came from
            tables = [self.schmetzer_scores_tables["all"]] + [
                self.schmetzer_scores_tables["season"].replace("YEAR", str(year))
                for year in self.get_schmetzer_season_tables(c)]
            for t in tables:
                self._upsert_table_to_supabase(supabase, c, t, self.SUPABASE_SCORE_COLUMNS,
                                               on_conflict='id', scored_rows_only=True)
            self._upsert_table_to_supabase(supabase, c, self.schmetzer_points_table,
                                           self.SUPABASE_SCHMETZER_POINTS_COLUMNS,
                                           on_conflict='stat_name')
        except sqlite3.Error as e:
            print(e)
        except FunctionsHttpError as exception:
            err = exception.to_dict()
            print(f'Function returned an error {err.get("message")}')
        except FunctionsRelayError as exception:
            err = exception.to_dict()
            print(f'Relay error: {err.get("message")}')
        finally:
            conn.close()
        

