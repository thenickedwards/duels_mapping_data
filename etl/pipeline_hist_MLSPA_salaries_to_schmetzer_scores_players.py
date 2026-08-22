import os
from dotenv import load_dotenv
load_dotenv()
from mlspa_data_handler import MLSPADataHandler
data_handler = MLSPADataHandler()

# Supabase credentials
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY")

def pipeline_hist_MLSPA_salaries_to_schmetzer_scores_players():
    ### Create this pipeline's tables and add the salary columns to existing score tables
    data_handler.create_salary_tables()
    data_handler.add_salary_columns_to_schmetzer_scores()

    ### Insert static data into dim tables
    data_handler.insert_dim_mls_club_crosswalk()

    ### Insert into raw table
    data_handler.insert_historical_raw_MLSPA_mls_players_salaries()

    ### Transform raw data for staging table
    data_handler.insert_stg_MLSPA_mls_players_salaries()

    ### Match salary records to the players already scored in schmetzer_scores_YYYY
    data_handler.match_stg_MLSPA_mls_players_salaries()

    ### Apply salaries to schmetzer_scores_players and derive the value metric (each table per season)
    data_handler.update_schmetzer_scores_players_salaries()

    ### Refresh schmetzer_scores_all so the all-seasons table carries the salary columns
    data_handler.insert_schmetzer_scores_all_seasons()

    ### Report how many scored players ended up with a salary
    data_handler.report_salary_coverage()

    # Upload SQLite data to Supabase
    data_handler.insert_SQLite_to_Supabase(supabase_url=SUPABASE_URL, supabase_key=SUPABASE_ANON_KEY)


if __name__ == "__main__":
    pipeline_hist_MLSPA_salaries_to_schmetzer_scores_players()
