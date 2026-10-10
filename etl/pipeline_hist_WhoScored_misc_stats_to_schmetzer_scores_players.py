from dotenv import load_dotenv
load_dotenv()
from dh_whoscored_misc_stats import DH_WhoScored
from dh_mlspa_salaries import DH_MLSPA
data_handler = DH_WhoScored()
salary_handler = DH_MLSPA()


def pipeline_hist_WhoScored_misc_stats_to_schmetzer_scores_players():
    seasons = data_handler.get_whoscored_seasons()

    ### Create this pipeline's tables, leaving the FBref tables alone
    data_handler.create_whoscored_tables()

    ### Insert static data into dim tables
    data_handler.insert_dim_mls_club_crosswalk()

    ### Insert into raw table (every WhoScored season, from first_season in dv_whoscored.json)
    data_handler.insert_historical_raw_WhoScored_mls_players_match_stats()

    ### Resolve players to a name, nationality and birth year
    data_handler.insert_dim_WhoScored_mls_players(seasons=seasons)

    ### Transform raw data for staging table
    data_handler.insert_stg_WhoScored_mls_players_all_stats_misc(seasons=seasons)

    ### Create and Insert into schmetzer_scores_players calculated points and scores (each table per season)
    data_handler.insert_schmetzer_scores_players(seasons=seasons)

    ### Rescoring drops the salary columns, so re-match and re-apply those seasons' salaries
    salary_handler.match_stg_MLSPA_mls_players_salaries(seasons=seasons)
    salary_handler.update_schmetzer_scores_players_salaries(seasons=seasons)

    ### Create and Insert into schmetzer_scores_all calculated points and scores (all seasons, one table)
    data_handler.insert_schmetzer_scores_all_seasons()

    ### Report anything the seasons are missing before they ship
    data_handler.report_whoscored_coverage(seasons=seasons)

    # Upload SQLite data to Supabase
    data_handler.insert_SQLite_to_Supabase()


if __name__ == "__main__":
    pipeline_hist_WhoScored_misc_stats_to_schmetzer_scores_players()
