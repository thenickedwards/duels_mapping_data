from dotenv import load_dotenv
load_dotenv()
from dh_mlspa_salaries import DH_MLSPA
data_handler = DH_MLSPA()


def pipeline_cur_MLSPA_salaries_to_schmetzer_scores_players():
    ### Make sure the salary columns exist on any season table added since the last run
    data_handler.add_salary_columns_to_schmetzer_scores()

    ### Refresh the crosswalk in case dv_clubs_cw.json gained a club since the last run
    data_handler.insert_dim_mls_club_crosswalk()

    ### Insert into raw table
    data_handler.insert_current_raw_MLSPA_mls_players_salaries()

    seasons = [max(data_handler.get_salary_seasons())]

    ### Transform raw data for staging table
    data_handler.insert_stg_MLSPA_mls_players_salaries(seasons=seasons)

    ### Match salary records to the players already scored in schmetzer_scores_YYYY
    data_handler.match_stg_MLSPA_mls_players_salaries(seasons=seasons)

    ### Apply salaries to schmetzer_scores_players and derive the value metric
    data_handler.update_schmetzer_scores_players_salaries(seasons=seasons)

    ### Refresh schmetzer_scores_all so the all-seasons table carries the salary columns
    data_handler.insert_schmetzer_scores_all_seasons()

    ### Report how many scored players ended up with a salary
    data_handler.report_salary_coverage()

    # Upload SQLite data to Supabase
    data_handler.insert_SQLite_to_Supabase()


if __name__ == "__main__":
    pipeline_cur_MLSPA_salaries_to_schmetzer_scores_players()
