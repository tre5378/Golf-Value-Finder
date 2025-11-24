import streamlit as st
import pandas as pd
from thefuzz import process
import os
import re

# --- Configuration ---
MANUAL_MATCHES_FILE = 'manual_matches.csv'

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

def get_country_flag(country_code):
    """Returns a flag emoji for a given country code."""
    flags = {"USA": "🇺🇸", "SCO": "🏴󠁧󠁢󠁳󠁣󠁴󠁿", "NIR": "🇬🇧", "ENG": "🏴󠁧󠁢󠁥󠁮󠁧󠁿", "IRL": "🇮🇪", "CAN": "🇨�", "AUS": "🇦🇺", "JPN": "🇯🇵", "KOR": "🇰🇷", "RSA": "🇿🇦", "ESP": "🇪🇸", "SWE": "🇸🇪", "NOR": "🇳🇴", "DEN": "🇩🇰", "FIN": "🇫🇮", "FRA": "🇫🇷", "GER": "🇩🇪", "ITA": "🇮🇹", "BEL": "🇧🇪", "AUT": "🇦🇹", "CHN": "🇨🇳", "TPE": "🇹🇼", "NZL": "🇳🇿", "VEN": "🇻🇪", "COL": "🇨🇴", "ARG": "🇦🇷", "UAE": "🇦🇪", "NED": "🇳🇱"}
    return flags.get(country_code, "🏳️")

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
    
    # Calculate Place odds based on the selected term (1/4 or 1/5)
    def calculate_place_odds(row):
        decimal_odds = fractional_to_decimal(row['Fractional Odds'])
        if decimal_odds is None:
            return None
        divisor = int(row['Place Term'].split('/')[1])
        return 1 + ((decimal_odds - 1) / divisor)

    pos_df['Bookmaker Odds'] = pos_df.apply(calculate_place_odds, axis=1)
    pos_df['DataGolf Odds'] = pos_df.apply(lambda row: pd.to_numeric(row.get(f"top_{row['Places']}"), errors='coerce'), axis=1)
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

def add_player_occurrence_count(df):
    """Adds a cumulative count to each player's name based on their appearance order."""
    # Make a copy to avoid SettingWithCopyWarning
    df_copy = df.copy()
    # cumcount is 0-based, so add 1 to start counting from 1
    df_copy['count'] = df_copy.groupby('Player').cumcount() + 1
    # Format the 'Player' column to include the count
    df_copy['Player'] = df_copy['Player'] + ' (' + df_copy['count'].astype(str) + ')'
    # Drop the temporary count column
    df_copy = df_copy.drop(columns=['count'])
    # Rename 'Player' to 'Points' as per user's previous request
    df_copy = df_copy.rename(columns={'Player': 'Points'})
    return df_copy

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
if 'bookmaker_df_3' not in st.session_state:
    st.session_state.bookmaker_df_3 = None
if 'bookmaker_df_4' not in st.session_state:
    st.session_state.bookmaker_df_4 = None
if 'event_name' not in st.session_state:
    st.session_state.event_name = "Value Finder"
if 'event_country' not in st.session_state:
    st.session_state.event_country = None

# --- Sidebar ---
st.sidebar.header("⚙️ Configuration")

# Bookmaker 1 Inputs
with st.sidebar.expander("Bookmaker 1 Settings", expanded=True):
    bookmaker_1_name = st.text_input("Bookmaker 1 Name", value="Bookmaker 1", key="name_1")
    bookmaker_1_places = st.number_input("Number of Places", min_value=1, value=5, key="places_1")
    place_term_1 = st.radio("Place Term", ["1/5", "1/4"], key="term_1", horizontal=True)
    uploaded_bookmaker_file_1 = st.file_uploader("Upload Bookmaker 1 Odds File", type="csv", key="upload_1")

# Bookmaker 2 Inputs
with st.sidebar.expander("Bookmaker 2 Settings"):
    bookmaker_2_name = st.text_input("Bookmaker 2 Name", value="Bookmaker 2", key="name_2")
    bookmaker_2_places = st.number_input("Number of Places", min_value=1, value=5, key="places_2")
    place_term_2 = st.radio("Place Term", ["1/5", "1/4"], key="term_2", horizontal=True)
    uploaded_bookmaker_file_2 = st.file_uploader("Upload Bookmaker 2 Odds File", type="csv", key="upload_2")

# Bookmaker 3 Inputs
with st.sidebar.expander("Bookmaker 3 Settings"):
    bookmaker_3_name = st.text_input("Bookmaker 3 Name", value="Bookmaker 3", key="name_3")
    bookmaker_3_places = st.number_input("Number of Places", min_value=1, value=5, key="places_3")
    place_term_3 = st.radio("Place Term", ["1/5", "1/4"], key="term_3", horizontal=True)
    uploaded_bookmaker_file_3 = st.file_uploader("Upload Bookmaker 3 Odds File", type="csv", key="upload_3")

# Bookmaker 4 Inputs
with st.sidebar.expander("Bookmaker 4 Settings"):
    bookmaker_4_name = st.text_input("Bookmaker 4 Name", value="Bookmaker 4", key="name_4")
    bookmaker_4_places = st.number_input("Number of Places", min_value=1, value=5, key="places_4")
    place_term_4 = st.radio("Place Term", ["1/5", "1/4"], key="term_4", horizontal=True)
    uploaded_bookmaker_file_4 = st.file_uploader("Upload Bookmaker 4 Odds File", type="csv", key="upload_4")

st.sidebar.divider()
st.sidebar.header("DataGolf Source")
uploaded_datagolf_file = st.sidebar.file_uploader("Upload DataGolf Odds File", type="csv", key="upload_dg")

st.sidebar.divider()
run_button = st.sidebar.button("Run Analysis", type="primary")

def clear_state():
    for key in st.session_state.keys():
        del st.session_state[key]
st.sidebar.button("Clear App State", on_click=clear_state, help="Click to clear all loaded data and start over.")
st.sidebar.divider()

# --- Main Page ---
flag_emoji = get_country_flag(st.session_state.event_country)
st.title(f"{flag_emoji} {st.session_state.event_name}")
st.markdown("Configure your data sources in the sidebar, then click 'Run Analysis'.")

# --- Data Loading Logic ---
if run_button:
    if not any([uploaded_bookmaker_file_1, uploaded_bookmaker_file_2, uploaded_bookmaker_file_3, uploaded_bookmaker_file_4]):
        st.warning("Please upload at least one bookmaker file.")
        st.stop()

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
    if uploaded_bookmaker_file_3:
        st.session_state.bookmaker_df_3 = pd.read_csv(uploaded_bookmaker_file_3, header=None, names=['Player', 'Fractional Odds'])
    if uploaded_bookmaker_file_4:
        st.session_state.bookmaker_df_4 = pd.read_csv(uploaded_bookmaker_file_4, header=None, names=['Player', 'Fractional Odds'])

    st.rerun()

# --- Main Analysis Block ---
if st.session_state.datagolf_df is not None and any([st.session_state.bookmaker_df_1 is not None, st.session_state.bookmaker_df_2 is not None, st.session_state.bookmaker_df_3 is not None, st.session_state.bookmaker_df_4 is not None]):
    try:
        datagolf_df = st.session_state.datagolf_df

        all_bookmaker_dfs = []
        bookmaker_options = {}
        
        # Process Bookmaker 1
        if st.session_state.bookmaker_df_1 is not None:
            df1 = st.session_state.bookmaker_df_1.copy()
            df1['Bookmaker'] = bookmaker_1_name
            df1['Places'] = bookmaker_1_places
            df1['Place Term'] = place_term_1
            all_bookmaker_dfs.append(df1)
            bookmaker_options[bookmaker_1_name] = st.session_state.bookmaker_df_1
        
        # Process Bookmaker 2
        if st.session_state.bookmaker_df_2 is not None:
            df2 = st.session_state.bookmaker_df_2.copy()
            df2['Bookmaker'] = bookmaker_2_name
            df2['Places'] = bookmaker_2_places
            df2['Place Term'] = place_term_2
            all_bookmaker_dfs.append(df2)
            bookmaker_options[bookmaker_2_name] = st.session_state.bookmaker_df_2
        
        # Process Bookmaker 3
        if st.session_state.bookmaker_df_3 is not None:
            df3 = st.session_state.bookmaker_df_3.copy()
            df3['Bookmaker'] = bookmaker_3_name
            df3['Places'] = bookmaker_3_places
            df3['Place Term'] = place_term_3
            all_bookmaker_dfs.append(df3)
            bookmaker_options[bookmaker_3_name] = st.session_state.bookmaker_df_3

        # Process Bookmaker 4
        if st.session_state.bookmaker_df_4 is not None:
            df4 = st.session_state.bookmaker_df_4.copy()
            df4['Bookmaker'] = bookmaker_4_name
            df4['Places'] = bookmaker_4_places
            df4['Place Term'] = place_term_4
            all_bookmaker_dfs.append(df4)
            bookmaker_options[bookmaker_4_name] = st.session_state.bookmaker_df_4

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
                                elif book_to_edit == bookmaker_3_name:
                                    st.session_state.bookmaker_df_3.loc[st.session_state.bookmaker_df_3['Player'] == player_to_edit, 'Fractional Odds'] = new_odds
                                elif book_to_edit == bookmaker_4_name:
                                    st.session_state.bookmaker_df_4.loc[st.session_state.bookmaker_df_4['Player'] == player_to_edit, 'Fractional Odds'] = new_odds
                                st.rerun()

            st.divider()

            win_df = process_win_market(base_comparison_df)
            pos_df = process_positional_market(base_comparison_df)
            ew_results = merge_and_calculate_ew(win_df, pos_df)
            
            # Add the occurrence count to the player names
            ew_results_with_counts = add_player_occurrence_count(ew_results)
            st.session_state.ew_results = ew_results_with_counts

            st.header("Each Way Value Analysis")
            display_results_table(st.session_state.ew_results, column_config={
                "Points": st.column_config.TextColumn("Points"),
                "Bookmaker": st.column_config.TextColumn(),
                "Bookmaker Odds": st.column_config.NumberColumn(format="%.2f"),
                "Each Way Value": st.column_config.ProgressColumn(
                    "Each Way Value", help="The average value across the Win and Positional markets.", format="%.2f%%",
                    min_value=float(ew_results["Each Way Value"].min()), max_value=float(ew_results["Each Way Value"].max()),
                ),
            })

            if not st.session_state.ew_results.empty:
                st.download_button(
                    label="📥 Download Each Way Analysis (CSV)",
                    data=st.session_state.ew_results.to_csv(index=False).encode('utf-8'),
                    file_name="each_way_value_analysis.csv",
                    mime='text/csv',
                )

            st.divider()

            with st.expander("Show Detailed Market Analysis"):
                st.header("Win Market Analysis")
                win_results_detailed = win_df[['Player', 'Bookmaker', 'Bookmaker Odds', 'DataGolf Odds', 'Win % Edge']].rename(columns={'Win % Edge': 'Value (% Edge)', 'Player': 'Points'})
                display_results_table(win_results_detailed, column_config={
                    "Points": st.column_config.TextColumn(),
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
                pos_results_detailed = pos_df[['Player', 'Bookmaker', 'Bookmaker Odds', 'DataGolf Odds', 'Positional % Edge']].rename(columns={'Positional % Edge': 'Value (% Edge)', 'Player': 'Points'})
                display_results_table(pos_results_detailed, column_config={
                    "Points": st.column_config.TextColumn(),
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
