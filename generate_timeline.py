"""
generate_visual_timeline.py

This script generates a visual timeline of each tracked person's activity (availability)
for sessions recorded in the presence_tracker.db database. Each page in the resulting PDF corresponds
to one session. The output files are saved in the "timelines" folder with a date-based filename.
"""

import json
import os
import sqlite3
from datetime import datetime, timedelta
from math import ceil

import matplotlib.patches as patches
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages

# Set the path to your database file and params.json
DB_FILE = "presence_tracker.db"
PARAMS_FILE = "params.json"


def parse_timestamp(timestamp_str):
    """
    Parse a timestamp string to a datetime object.
    """
    try:
        timestamp_str = timestamp_str.replace("T", " ")
        return datetime.fromisoformat(timestamp_str)
    except Exception as exc:
        print(f"Error parsing timestamp '{timestamp_str}': {exc}")
        return None


def get_tracked_users(conn):
    """
    Retrieve users from the database.
    """
    users = {}
    cursor = conn.cursor()
    cursor.execute("SELECT id, mail, display_name FROM User")
    for row in cursor.fetchall():
        user_id = row[0]
        name = row[2] if row[2] else row[1]
        users[user_id] = name
    return users


def get_sessions(conn, report_days):
    """
    Retrieve sessions from the database that started after a cutoff date.
    """
    cutoff = datetime.now() - timedelta(days=report_days)
    cutoff_str = cutoff.isoformat(sep=" ", timespec="seconds")
    cursor = conn.cursor()
    cursor.execute("SELECT id, start_time, end_time FROM Session WHERE start_time >= ? ORDER BY start_time ASC", (cutoff_str,))
    sessions = cursor.fetchall()
    return sessions


def get_presence_for_session(conn, session_id):
    """
    Retrieve presence records for a session.
    """
    cursor = conn.cursor()
    cursor.execute("""SELECT user_id, start_time, end_time FROM Presence WHERE session_id = ? ORDER BY start_time ASC""", (session_id,))
    records = cursor.fetchall()
    return records


def plot_session_timeline(session, presences, users):
    """
    Create a timeline plot for a given session.
    """
    session_id, session_start_str, session_end_str = session
    session_start = parse_timestamp(session_start_str)
    session_end = parse_timestamp(session_end_str)
    if not session_start or not session_end:
        return None

    session_duration_minutes = (session_end - session_start).total_seconds() / 60

    # Sort usernames alphabetically
    tracked_user_ids = list(set([r[0] for r in presences]))
    tracked_user_ids.sort(key=lambda uid: users.get(uid, f"User {uid}").lower())

    user_segments = {uid: [] for uid in tracked_user_ids}
    for rec in presences:
        uid, p_start_str, p_end_str = rec
        p_start = parse_timestamp(p_start_str)
        p_end = parse_timestamp(p_end_str)
        if p_start is None or p_end is None:
            continue
        effective_start = max(p_start, session_start)
        effective_end = min(p_end, session_end)
        if effective_end <= effective_start:
            continue
        start_minute = (effective_start - session_start).total_seconds() / 60
        duration_min = (effective_end - effective_start).total_seconds() / 60
        user_segments[uid].append((start_minute, duration_min))

    fig, ax = plt.subplots(figsize=(12, 1 + 0.5 * len(tracked_user_ids)))

    y_ticks = []
    y_labels = []
    for idx, uid in enumerate(tracked_user_ids):
        # Reverse the order
        y_pos = len(tracked_user_ids) - idx - 1
        y_ticks.append(y_pos + 0.5)
        name = users.get(uid, f"User {uid}")
        y_labels.append(name)

        # Draw the entire row as unavailable (green as base)
        ax.add_patch(patches.Rectangle((0, y_pos), session_duration_minutes, 0.8, color="green"))

        # Draw the user-specific unavailability segments (gray)
        for (seg_start, seg_duration) in user_segments[uid]:
            rect = patches.Rectangle((seg_start, y_pos), seg_duration, 0.8, color="gray")
            ax.add_patch(rect)

        ax.hlines(y=y_pos, xmin=0, xmax=session_duration_minutes, color="white", linewidth=0.8)

    # Customize x-axis to display times of the session
    total_minutes = int(session_duration_minutes)

    # Find the first full hour after the session start time
    session_start_hour_minute = session_start.hour * 60 + session_start.minute
    first_tick_minutes = ceil(session_start_hour_minute / 60) * 60 - session_start_hour_minute

    # Hourly ticks and ensure the last tick matches session end
    x_ticks = list(range(first_tick_minutes, total_minutes, 60))  # Hourly ticks
    if total_minutes not in x_ticks:  # Explicitly include the end of the session
        x_ticks.append(total_minutes)

    # Generate corresponding x-axis labels
    x_labels = [(session_start + timedelta(minutes=minute)).strftime("%H:%M") for minute in x_ticks]
    x_ticks[-1] = total_minutes  # Ensure last tick matches session duration
    x_labels[-1] = session_end.strftime("%H:%M")  # Ensure exact end time as label

    # Set axes and labels
    ax.set_xticks(x_ticks)
    ax.set_xticklabels(x_labels, rotation=45)

    ax.set_xlim(0, x_ticks[-1])  # Match x-axis to end of session
    ax.set_ylim(0, len(tracked_user_ids))
    ax.set_xlabel("Time of Day")
    ax.set_yticks(y_ticks)
    ax.set_yticklabels(y_labels)
    ax.set_title(f"Session {session_id} - {session_start.strftime('%Y-%m-%d %H:%M')} to {session_end.strftime('%H:%M')}")
    ax.grid(axis="x", linestyle="--", linewidth=0.5, alpha=0.7)

    plt.tight_layout()
    return fig


def load_params():
    """
    Load parameters from params.json.
    """
    if not os.path.exists(PARAMS_FILE):
        raise FileNotFoundError(f"Params file '{PARAMS_FILE}' not found.")
    with open(PARAMS_FILE, "r") as f:
        return json.load(f)


def main():
    # Load params.json
    params = load_params()
    report_days = params.get("report_days", 7)

    # Prepare the output folder
    output_dir = "timelines"
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    # Connect to the database
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row

    # Get tracked users
    users = get_tracked_users(conn)

    # Get sessions
    sessions = get_sessions(conn, report_days)
    if not sessions:
        print("No sessions found for the given report_days criteria.")
        return

    # Generate filenames with date range
    earliest_date = parse_timestamp(sessions[0][1]).strftime("%Y-%m-%d")
    latest_date = parse_timestamp(sessions[-1][1]).strftime("%Y-%m-%d")
    output_file = os.path.join(output_dir, f"{earliest_date}_to_{latest_date}_visual_timeline.pdf")

    # Create a multi-page PDF
    with PdfPages(output_file) as pdf:
        for session in sessions:
            session_id = session[0]
            presences = get_presence_for_session(conn, session_id)
            if not presences:
                continue
            fig = plot_session_timeline(session, presences, users)
            if fig is not None:
                pdf.savefig(fig)
                plt.close(fig)
                print(f"Added timeline for session {session_id} to the PDF.")

    conn.close()
    print(f"Visual timeline PDF generated as '{output_file}'.")


if __name__ == "__main__":
    main()
