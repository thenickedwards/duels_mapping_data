from dotenv import load_dotenv
load_dotenv()
from data_handler import DataHandler
data_handler = DataHandler()




def pipeline_hist_SQLite_to_Supabase():
    # Upload SQLite data to Supabase
    data_handler.insert_SQLite_to_Supabase()




if __name__ == "__main__":
    pipeline_hist_SQLite_to_Supabase()