#!/usr/bin/env python3
"""
generate_visual_timeline.py

This script generates a visual timeline of each tracked person's activity (availability)
for sessions recorded in the presence_tracker.db database. Each page in the resulting PDF
corresponds to one session. The x-axis represents time (in minutes from the session start),
and each row represents a tracked user, with available periods shown in green.
"""

import argparse
import sqlite3
from datetime import datetime, timedelta
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
import matplotlib.patches as patches

# Set the path to your database file
DB_FILE = "presence_tracker.db"


def parse_timestamp(timestamp_str):
    """
    Parse a timestamp string to a datetime object.
    Assumes ISO8601 format; adjust if needed.
    """
    try:
        # Replace "T" with a space if necessary.
        timestamp_str = timestamp_str.replace("T", " ")
        return datetime.fromisoformat(timestamp_str)
    except Exception as exc:
        print(f"Error parsing timestamp '{timestamp_str}': {exc}")
        return None


def get_tracked_users(conn):
    """
    Retrieve users from the database.
    Assumes there is a table named "User" with columns "id", "mail", and "display_name".
    """
    users = {}
    cursor = conn.cursor()
    cursor.execute("SELECT id, mail, display_name FROM User")
    for row in cursor.fetchall():
        user_id = row[0]
        # Prefer display name if available; otherwise, use email.
        name = row[2] if row[2] else row[1]
        users[user_id] = name
    return users


def get_sessions(conn, report_days):
    """
    Retrieve sessions from the database that started after a cutoff date.
    Assumes a table named "Session" with columns "id", "start_time", and "end_time".
    """
    cutoff = datetime.now() - timedelta(days=report_days)
    cutoff_str = cutoff.isoformat(sep=" ", timespec="seconds")
    cursor = conn.cursor()
    cursor.execute("SELECT id, start_time, end_time FROM Session WHERE start_time >= ? ORDER BY start_time ASC",
                   (cutoff_str,))
    sessions = cursor.fetchall()
    return sessions


def get_presence_for_session(conn, session_id):
    """
    Retrieve presence records for a session.
    Assumes a table named "Presence" with columns "session_id", "user_id", "start_time", "end_time".
    """
    cursor = conn.cursor()
    cursor.execute("""SELECT user_id, start_time, end_time FROM Presence WHERE session_id = ? ORDER BY start_time ASC""", (session_id,))
    records = cursor.fetchall()
    return records


def plot_session_timeline(session, presences, users):
    """
    Create a timeline plot for a given session.
    - session: tuple (session_id, start_time, end_time)
    - presences: list of tuples (user, start_time, end_time)
    - users: dict mapping user id to display name.
    """
    session_id, session_start_str, session_end_str = session
    session_start = parse_timestamp(session_start_str)
    session_end = parse_timestamp(session_end_str)
    if not session_start or not session_end:
        return None

    session_duration_minutes = (session_end - session_start).total_seconds() / 60

    # Determine the list of tracked user ids that have any presence in this session
    tracked_user_ids = set([r[0] for r in presences])
    # If a user is tracked but did not have any recorded presence in this session,
    # you may want to include them with an entirely unavailable timeline.
    # For now, we include only those with some presence records.
    tracked_user_ids = list(tracked_user_ids)
    tracked_user_ids.sort()

    # Create a mapping of user id -> list of presence segments (start, end in minutes from session_start)
    user_segments = {uid: [] for uid in tracked_user_ids}
    for rec in presences:
        uid, p_start_str, p_end_str = rec
        p_start = parse_timestamp(p_start_str)
        p_end = parse_timestamp(p_end_str)
        if p_start is None or p_end is None:
            continue
        # Clip the presence segment to the session boundaries:
        effective_start = max(p_start, session_start)
        effective_end = min(p_end, session_end)
        if effective_end <= effective_start:
            continue
        start_minute = (effective_start - session_start).total_seconds() / 60
        duration_min = (effective_end - effective_start).total_seconds() / 60
        user_segments[uid].append((start_minute, duration_min))

    # Begin plotting
    fig, ax = plt.subplots(figsize=(12, 1 + 0.5 * len(tracked_user_ids)))

    # For each user, add their available segments as green rectangles.
    y_ticks = []
    y_labels = []
    # Let row 0 be at the top, so reverse order if desired.
    for idx, uid in enumerate(tracked_user_ids):
        y_pos = len(tracked_user_ids) - idx - 1  # so first user at top
        y_ticks.append(y_pos + 0.5)
        name = users.get(uid, f"User {uid}")
        y_labels.append(name)
        # Draw each available segment as a rectangle:
        for (seg_start, seg_duration) in user_segments[uid]:
            rect = patches.Rectangle((seg_start, y_pos), seg_duration, 0.8, color="green")
            ax.add_patch(rect)
        # Optionally, draw a horizontal line to denote the row boundary:
        ax.hlines(y=y_pos, xmin=0, xmax=session_duration_minutes, color="gray", linewidth=0.5)

    ax.set_xlim(0, session_duration_minutes)
    ax.set_ylim(0, len(tracked_user_ids))
    ax.set_xlabel("Minutes from session start")
    ax.set_yticks(y_ticks)
    ax.set_yticklabels(y_labels)
    ax.set_title(f"Session {session_id} - {session_start.strftime('%Y-%m-%d %H:%M')} to {session_end.strftime('%H:%M')}")
    ax.grid(axis="x", linestyle="--", linewidth=0.5, alpha=0.7)

    plt.tight_layout()
    return fig


def main():
    parser = argparse.ArgumentParser(
        description="Generate a visual timeline of tracked person activity per session."
    )
    parser.add_argument(
        "--report_days",
        type=int,
        default=7,
        help="Number of days to generate sessions for (default: 7)"
    )
    parser.add_argument(
        "--output",
        type=str,
        default="visual_timeline.pdf",
        help="Output filename for the generated PDF (default: visual_timeline.pdf)"
    )
    args = parser.parse_args()

    # Connect to the database
    conn = sqlite3.connect(DB_FILE)
    # Enable dict-like access if needed:
    conn.row_factory = sqlite3.Row

    # Get tracked users from the database
    users = get_tracked_users(conn)

    # Get sessions for the given report_days
    sessions = get_sessions(conn, args.report_days)
    if not sessions:
        print("No sessions found for the given report_days criteria.")
        return

    # Create a multi-page PDF where each page is one session's timeline
    with PdfPages(args.output) as pdf:
        for session in sessions:
            session_id = session[0]
            # Query presence records for this session
            presences = get_presence_for_session(conn, session_id)
            # Only plot if there is presence data
            if not presences:
                continue
            fig = plot_session_timeline(session, presences, users)
            if fig is not None:
                pdf.savefig(fig)
                plt.close(fig)
                print(f"Added timeline for session {session_id} to the PDF.")

    conn.close()
    print(f"Visual timeline PDF generated as '{args.output}'.")


if __name__ == "__main__":
    main()
