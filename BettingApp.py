import streamlit as st
import pandas as pd
from thefuzz import process
import os
import re
import gspread
from gspread_dataframe import set_with_dataframe
from google.oauth2.service_account import Credentials
from google.auth.exceptions import DefaultCredentialsError
import requests

# --- Configuration ---
MANUAL_MATCHES_FILE = 'manual_matches.csv'
GSHEET_CREDENTIALS_FILE = 'gsheet_credentials.json'
GSHEET_SCOPES = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive",
]

# --- Helper Functions ---

def fractional_to_decimal(fractional_odds):
    """Converts fractional odds string (e.g., '10/1') to decimal odds (e.g., 11.0)."""
    try:
        if isinstance(fractional_odds, str) and '/' in fractional_odds:
            num, den = map(int, fractional_odds.split('/'))
            return (num / den) + 1.0
        return float(fractional_odds)
    except (ValueError, TypeError):
        return None

def find_best_match(name, choices, score_cutoff=90):
    """Finds the best fuzzy match for a name from a list of choices."""
    best_match = process.extractOne(name, choices, score_cutoff=score_cutoff)
    return best_match[0] if best_match else None

def load_manual_mappings():
    """Loads manual name mappings from a local CSV file if it exists."""
    if os.path.exists(MANUAL_MATCHES_FILE):
        return pd.read_csv(MANUAL_MATCHES_FILE).set_index('bookmaker_name')['datagolf_name'].to_dict()
    return {}

def save_manual_mappings(mappings_dict):
    """Saves the manual name mappings to a local CSV file."""
    mappings_df = pd.DataFrame(list(mappings_dict.items()), columns=['bookmaker_name', 'datagolf_name'])
    mappings_df.to_csv(MANUAL_MATCHES_FILE, index=False)

def export_to_gsheet(df, sheet_name, worksheet_name="Each Way Value"):
    """Exports a DataFrame to the specified Google Sheet."""
    try:
        if not os.path.exists(GSHEET_CREDENTIALS_FILE):
            st.sidebar.error(f"'{GSHEET_CREDENTIALS_FILE}' not found. Please follow the setup instructions.")
            return
        creds = Credentials.from_service_account_file(GSHEET_CREDENTIALS_FILE, scopes=GSHEET_SCOPES)
        gc = gspread.authorize(creds)
        spreadsheet = gc.open(sheet_name)
        try:
            worksheet = spreadsheet.worksheet(worksheet_name)
        except gspread.exceptions.WorksheetNotFound:
            worksheet = spreadsheet.add_worksheet(title=worksheet_name, rows="1000", cols="20")
        worksheet.clear()
        set_with_dataframe(worksheet, df)
        st.sidebar.success(f"Data exported to '{sheet_name}'!")
    except Exception as e:
        st.sidebar.error(f"An error occurred during export: {e}")

def get_country_flag(country_code):
    """Returns a flag emoji for a given country code."""
    flags = {"USA": "🇺🇸", "SCO": "🏴󠁧󠁢󠁳󠁣󠁴󠁿", "NIR": "🇬🇧", "ENG": "🏴󠁧󠁢󠁥󠁮󠁧󠁿", "IRL": "🇮🇪", "CAN": "🇨🇦", "AUS": "🇦🇺", "JPN": "🇯🇵", "KOR": "🇰🇷", "RSA": "🇿🇦", "ESP": "🇪🇸", "SWE": "🇸🇪", "NOR": "🇳🇴", "DEN": "🇩🇰", "FIN": "🇫🇮", "FRA": "🇫🇷", "GER": "🇩🇪", "ITA": "🇮🇹", "BEL": "🇧🇪", "AUT": "🇦🇹", "CHN": "🇨🇳", "TPE": "🇹🇼", "NZL": "🇳🇿", "VEN": "🇻🇪", "COL": "🇨🇴", "ARG": "🇦🇷", "UAE": "🇦🇪", "NED": "🇳🇱"}
    return flags.get(country_code, "🏳️")

def fetch_datagolf_data(api_key, tour):
    """Fetches pre-tournament predictions and metadata from the DataGolf API."""
    url = f"https://feeds.datagolf.com/preds/pre-tournament?tour={tour}&odds_format=decimal&key={api_key}"
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
    
    try:
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        data = response.json()

        event_name = data.get('event_name', 'Golf Event')
        
        pred_key = None
        if 'preds' in data and data['preds']:
            pred_key = 'preds'
        elif 'baseline_history_fit' in data and data['baseline_history_fit']:
            pred_key = 'baseline_history_fit'
        elif 'baseline' in data and data['baseline']:
            pred_key = 'baseline'

        if pred_key:
            df = pd.DataFrame(data[pred_key])
            country = df['country'].iloc[0] if not df.empty else None
            return df, event_name, country
        else:
            st.error("API Error: No valid prediction data found in the response.")
            return None, event_name, None

    except Exception as e:
        st.error(f"An error occurred while fetching data: {e}")
        return None, "Error", None

def display_results_table(results_df, column_config):
    """Renders the results DataFrame in a styled table."""
    st.dataframe(results_df, use_container_width=True, column_config=column_config, hide_index=True)

def process_win_market(base_comparison_df):
    """Processes the win market analysis."""
    win_df = base_comparison_df.copy()
    win_df['Bookmaker Odds'] = win_df['Fractional Odds'].apply(fractional_to_decimal)
    win_df['DataGolf Odds'] = pd.to_numeric(win_df['win'], errors='coerce')
    win_df.dropna(subset=['Bookmaker Odds', 'DataGolf Odds'], inplace=True)
    win_df['Win % Edge'] = ((win_df['Bookmaker Odds'] / win_df['DataGolf Odds']) - 1) * 100
    return win_df

def process_positional_market(base_comparison_df):
    """Processes the positional market analysis."""
    pos_df = base_comparison_df.copy()
    pos_df['DataGolf Odds'] = pos_df.apply(lambda row: pd.to_numeric(row.get(f"top_{row['Places']}"), errors='coerce'), axis=1)
    decimal_odds = pos_df['Fractional Odds'].apply(fractional_to_decimal)
    pos_df['Bookmaker Odds'] = 1 + ((decimal_odds - 1) / 5)
    pos_df.dropna(subset=['Bookmaker Odds', 'DataGolf Odds'], inplace=True)
    pos_df['Positional % Edge'] = ((pos_df['Bookmaker Odds'] / pos_df['DataGolf Odds']) - 1) * 100
    return pos_df

def merge_and_calculate_ew(win_df, pos_df):
    """Merges win and positional dataframes and calculates Each Way Value."""
    ew_df = pd.merge(
        win_df[['Player', 'Bookmaker', 'Bookmaker Odds', 'Win % Edge']],
        pos_df[['Player', 'Bookmaker', 'Positional % Edge']],
        on=['Player', 'Bookmaker']
    )
    ew_df['Each Way Value'] = (ew_df['Win % Edge'] + ew_df['Positional % Edge']) / 2
    ew_results = ew_df[['Player', 'Bookmaker', 'Bookmaker Odds', 'Each Way Value']].sort_values(by='Each Way Value', ascending=False)
    return ew_results

# --- Main App Logic ---
st.set_page_config(page_title="Value Finder", layout="wide")

# --- Initialize Session State ---
if 'ew_results' not in st.session_state:
    st.session_state.ew_results = pd.DataFrame()
if 'datagolf_df' not in st.session_state:
    st.session_state.datagolf_df = None
if 'bookmaker_df_1' not in st.session_state:
    st.session_state.bookmaker_df_1 = None
if 'bookmaker_df_2' not in st.session_state:
    st.session_state.bookmaker_df_2 = None
if 'event_name' not in st.session_state:
    st.session_state.event_name = "Value Finder"
if 'event_country' not in st.session_state:
    st.session_state.event_country = None

# --- Sidebar ---
st.sidebar.header("⚙️ Configuration")

# Bookmaker 1 Inputs
with st.sidebar.expander("Bookmaker 1 Settings", expanded=True):
    bookmaker_1_name = st.text_input("Bookmaker 1 Name", value="Bookmaker 1")
    bookmaker_1_places = st.number_input("Number of Places", min_value=1, value=5, key="places_1")
    uploaded_bookmaker_file_1 = st.file_uploader("Upload Bookmaker 1 Odds File", type="csv")

# Bookmaker 2 Inputs
with st.sidebar.expander("Bookmaker 2 Settings"):
    bookmaker_2_name = st.text_input("Bookmaker 2 Name", value="Bookmaker 2")
    bookmaker_2_places = st.number_input("Number of Places", min_value=1, value=5, key="places_2")
    uploaded_bookmaker_file_2 = st.file_uploader("Upload Bookmaker 2 Odds File", type="csv")

st.sidebar.divider()
st.sidebar.header("DataGolf Source")
data_source = st.sidebar.radio("Select DataGolf data source:", ["API", "File Upload"], horizontal=True)

if data_source == "API":
    try:
        default_api_key = st.secrets.get("datagolf_api_key", "")
    except FileNotFoundError:
        default_api_key = os.environ.get("DATAGOLF_API_KEY", "")
        
    api_key = st.sidebar.text_input("Enter your DataGolf API Key", type="password", value=default_api_key)
    tour = st.sidebar.selectbox("Select Tour", ["pga", "euro", "kft", "opp", "liv"])
else:
    uploaded_datagolf_file = st.sidebar.file_uploader("Upload DataGolf Odds File", type="csv")

st.sidebar.divider()
run_button = st.sidebar.button("Run Analysis", type="primary")

def clear_state():
    for key in st.session_state.keys():
        del st.session_state[key]
st.sidebar.button("Clear App State", on_click=clear_state, help="Click to clear all loaded data and start over.")
st.sidebar.divider()

# --- Google Sheets Export UI ---
st.sidebar.header("📤 Export to Google Sheets")
gsheet_name = st.sidebar.text_input("Google Sheet Name")
export_button = st.sidebar.button("Send to Google Sheet")

with st.sidebar.expander("Show Google Sheets Setup Instructions"):
    st.markdown("""
    To use this feature, you need to authenticate with Google Sheets...
    """) # Instructions hidden for brevity

# --- Main Page ---
flag_emoji = get_country_flag(st.session_state.event_country)
st.title(f"{flag_emoji} {st.session_state.event_name}")
st.markdown("Configure your data sources in the sidebar, then click 'Run Analysis'.")

# --- Data Loading Logic ---
if run_button:
    if not uploaded_bookmaker_file_1 and not uploaded_bookmaker_file_2:
        st.warning("Please upload at least one bookmaker file.")
        st.stop()

    if data_source == "API":
        if not api_key:
            st.warning("Please enter your DataGolf API key.")
            st.stop()
        with st.spinner("Fetching DataGolf API data..."):
            st.session_state.datagolf_df, st.session_state.event_name, st.session_state.event_country = fetch_datagolf_data(api_key, tour)
    else: # File Upload
        if not uploaded_datagolf_file:
            st.warning("Please upload a DataGolf file.")
            st.stop()
        st.session_state.datagolf_df = pd.read_csv(uploaded_datagolf_file)
        st.session_state.event_name = "Custom Event"
        st.session_state.event_country = None
    
    if uploaded_bookmaker_file_1:
        st.session_state.bookmaker_df_1 = pd.read_csv(uploaded_bookmaker_file_1, header=None, names=['Player', 'Fractional Odds'])
    if uploaded_bookmaker_file_2:
        st.session_state.bookmaker_df_2 = pd.read_csv(uploaded_bookmaker_file_2, header=None, names=['Player', 'Fractional Odds'])
    
    st.rerun()

# --- Main Analysis Block ---
if st.session_state.datagolf_df is not None and (st.session_state.bookmaker_df_1 is not None or st.session_state.bookmaker_df_2 is not None):
    try:
        datagolf_df = st.session_state.datagolf_df
        
        all_bookmaker_dfs = []
        bookmaker_options = {}
        if st.session_state.bookmaker_df_1 is not None:
            df1 = st.session_state.bookmaker_df_1.copy()
            df1['Bookmaker'] = bookmaker_1_name
            df1['Places'] = bookmaker_1_places
            all_bookmaker_dfs.append(df1)
            bookmaker_options[bookmaker_1_name] = st.session_state.bookmaker_df_1
        if st.session_state.bookmaker_df_2 is not None:
            df2 = st.session_state.bookmaker_df_2.copy()
            df2['Bookmaker'] = bookmaker_2_name
            df2['Places'] = bookmaker_2_places
            all_bookmaker_dfs.append(df2)
            bookmaker_options[bookmaker_2_name] = st.session_state.bookmaker_df_2
        
        bookmaker_df = pd.concat(all_bookmaker_dfs, ignore_index=True)

        manual_mappings = load_manual_mappings()
        datagolf_player_list = datagolf_df['player_name'].unique().tolist()

        def get_match(name):
            if name in manual_mappings:
                return manual_mappings[name]
            return find_best_match(name, datagolf_player_list, score_cutoff=90)

        bookmaker_df['matched_player'] = bookmaker_df['Player'].apply(get_match)
        unmatched_players = bookmaker_df[bookmaker_df['matched_player'].isnull()]['Player'].tolist()

        if unmatched_players:
            st.warning(f"Found {len(unmatched_players)} players that could not be automatically matched.")
            with st.expander("🔗 Manually Match Unmatched Players", expanded=True):
                unmatched_choice = st.selectbox("Select Unmatched Bookmaker Player:", options=unmatched_players)
                datagolf_choice = st.selectbox(f"Find Match for '{unmatched_choice}' in DataGolf List:", options=sorted(datagolf_player_list))
                if st.button("💾 Save Match"):
                    manual_mappings[unmatched_choice] = datagolf_choice
                    save_manual_mappings(manual_mappings)
                    st.success(f"Saved match: '{unmatched_choice}' -> '{datagolf_choice}'. The app will now refresh.")
                    st.rerun()

        base_comparison_df = pd.merge(
            bookmaker_df.dropna(subset=['matched_player']), datagolf_df,
            left_on='matched_player', right_on='player_name', how='inner'
        )

        if not base_comparison_df.empty:
            st.success(f"Comparison complete! Found {len(base_comparison_df)} matching players.")
            
            # --- Editable Odds Section ---
            with st.expander("✏️ Edit Player Odds"):
                book_to_edit = st.selectbox("Select Bookmaker to Edit", options=list(bookmaker_options.keys()))
                if book_to_edit:
                    df_to_edit = bookmaker_options[book_to_edit]
                    player_to_edit = st.selectbox("Select Player to Edit", options=sorted(df_to_edit['Player'].unique()))
                    if player_to_edit:
                        current_odds = df_to_edit.loc[df_to_edit['Player'] == player_to_edit, 'Fractional Odds'].iloc[0]
                        new_odds = st.text_input("New Fractional Odds", value=current_odds, key=f"edit_{book_to_edit}_{player_to_edit}")
                        if st.button("Update Odds", key=f"update_{book_to_edit}_{player_to_edit}"):
                            if new_odds != current_odds:
                                if book_to_edit == bookmaker_1_name:
                                    st.session_state.bookmaker_df_1.loc[st.session_state.bookmaker_df_1['Player'] == player_to_edit, 'Fractional Odds'] = new_odds
                                elif book_to_edit == bookmaker_2_name:
                                    st.session_state.bookmaker_df_2.loc[st.session_state.bookmaker_df_2['Player'] == player_to_edit, 'Fractional Odds'] = new_odds
                                st.rerun()
            
            st.divider()

            # --- Calculations ---
            win_df = process_win_market(base_comparison_df)
            pos_df = process_positional_market(base_comparison_df)
            ew_results = merge_and_calculate_ew(win_df, pos_df)
            st.session_state.ew_results = ew_results

            # --- Main Page: Each Way Value Analysis ---
            st.header("Each Way Value Analysis")
            display_results_table(ew_results, column_config={
                "Bookmaker": st.column_config.TextColumn(),
                "Bookmaker Odds": st.column_config.NumberColumn(format="%.2f"),
                "Each Way Value": st.column_config.ProgressColumn(
                    "Each Way Value", help="The average value across the Win and Positional markets.", format="%.2f%%",
                    min_value=float(ew_results["Each Way Value"].min()), max_value=float(ew_results["Each Way Value"].max()),
                ),
            })
            
            if not ew_results.empty:
                st.download_button(
                    label="📥 Download Each Way Analysis (CSV)",
                    data=ew_results.to_csv(index=False).encode('utf-8'),
                    file_name="each_way_value_analysis.csv",
                    mime='text/csv',
                )

            st.divider()

            # --- Secondary Page: Detailed Market Analysis ---
            with st.expander("Show Detailed Market Analysis"):
                st.header("Win Market Analysis")
                win_results_detailed = win_df[['Player', 'Bookmaker', 'Bookmaker Odds', 'DataGolf Odds', 'Win % Edge']].rename(columns={'Win % Edge': 'Value (% Edge)'})
                display_results_table(win_results_detailed, column_config={
                    "Bookmaker": st.column_config.TextColumn(),
                    "Bookmaker Odds": st.column_config.NumberColumn(format="%.2f"),
                    "DataGolf Odds": st.column_config.NumberColumn(format="%.2f"),
                    "Value (% Edge)": st.column_config.ProgressColumn(
                        "Value (% Edge)", format="%.2f%%",
                        min_value=float(win_results_detailed["Value (% Edge)"].min()),
                        max_value=float(win_results_detailed["Value (% Edge)"].max()),
                    ),
                })

                st.header("Positional Market Analysis")
                pos_results_detailed = pos_df[['Player', 'Bookmaker', 'Bookmaker Odds', 'DataGolf Odds', 'Positional % Edge']].rename(columns={'Positional % Edge': 'Value (% Edge)'})
                display_results_table(pos_results_detailed, column_config={
                    "Bookmaker": st.column_config.TextColumn(),
                    "Bookmaker Odds": st.column_config.NumberColumn(format="%.2f"),
                    "DataGolf Odds": st.column_config.NumberColumn(format="%.2f"),
                    "Value (% Edge)": st.column_config.ProgressColumn(
                        "Value (% Edge)", format="%.2f%%",
                        min_value=float(pos_results_detailed["Value (% Edge)"].min()),
                        max_value=float(pos_results_detailed["Value (% Edge)"].max()),
                    ),
                })

        elif not unmatched_players:
            st.info("No matching players found.")
    except Exception as e:
        st.error(f"An error occurred during processing: {e}")

# Handle Export Button Click
if export_button:
    if gsheet_name:
        if 'ew_results' in st.session_state and not st.session_state.ew_results.empty:
            export_to_gsheet(st.session_state.ew_results, gsheet_name)
        else:
            st.sidebar.warning("No data available to export. Please run the analysis first.")
    else:
        st.sidebar.warning("Please enter a Google Sheet name.")