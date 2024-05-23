import json
import sqlite3
import csv
from collections import defaultdict
from datetime import datetime, timedelta, date

# Load parameters from JSON file
with open("params.json") as f:
    params = json.load(f)

# Get the number of days from params report_days value
report_days = params.get("report_days", 365)
if report_days < 1:
    report_days = 1


# Convert seconds to minutes and round it off
def seconds_to_minutes(seconds):
    return round(seconds / 60)


# Connect to the SQLite DB
conn = sqlite3.connect("presence_tracker.db")
cursor = conn.cursor()

# Calculate start date, "report_days" in the past
date_report_days_ago = datetime.now() - timedelta(days=report_days)

# Count the number of days with sessions, excluding weekends
cursor.execute(
    """
    SELECT DISTINCT DATE(start_time) AS session_day
    FROM session
    WHERE start_time >= ?
    """, (date_report_days_ago,)
)
session_days = sum(1 for row in cursor.fetchall() if date.fromisoformat(row[0]).weekday() < 5)

# Get the total seconds of all sessions combined
cursor.execute(
    """
    SELECT SUM((julianday(end_time) - julianday(start_time)) * 24 * 60 * 60)
    FROM session
    WHERE start_time >= ?
    """, (date_report_days_ago,)
)
total_session_seconds = cursor.fetchone()[0]

# Get total presence for each user, total duration and average duration per session in the last report_days
cursor.execute(
    """
    SELECT user_id, COUNT(*), SUM(duration_seconds)
    FROM presence
    WHERE start_time >= ?
    GROUP BY user_id
    """, (date_report_days_ago,)
)

# Data dictionary to hold presence information by user email
user_presence = defaultdict(dict)
for user_id, presence_changes, total_unavailability_seconds in cursor.fetchall():
    # Get user name and email
    cursor.execute("SELECT display_name, mail FROM user WHERE id = ?", (user_id,))
    user_name, user_email = cursor.fetchone()
    
    user_presence[user_name]["User Email"] = user_email
    user_presence[user_name]["Unavailability Percentage"] = min(1.0, round(0 if total_session_seconds == 0 else total_unavailability_seconds / total_session_seconds, 2))
    user_presence[user_name]["Unavailability Minutes Daily Average"] = seconds_to_minutes(total_unavailability_seconds / session_days)
    user_presence[user_name]["Unavailability Minutes Total"] = seconds_to_minutes(total_unavailability_seconds)
    user_presence[user_name]["Go Unavailable Daily Frequency"] = round(presence_changes / session_days, 2)
    user_presence[user_name]["Go Unavailable Total"] = presence_changes

# Close the DB connection
cursor.close()
conn.close()

# Start building report CSV
fields = [
    "User Name",
    "User Email",
    "Unavailability Percentage",
    "Unavailability Minutes Daily Average",
    "Unavailability Minutes Total",
    "Go Unavailable Daily Frequency",
    "Go Unavailable Total"
]

# Sort the result based on Unavailability Percentage in descending order
sorted_user_presence = dict(sorted(user_presence.items(), key=lambda item: item[1]["Unavailability Percentage"], reverse=True))

# Write the results to a file
with open("report.csv", "w", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=fields)
    writer.writeheader()
    for name, data in sorted_user_presence.items():
        writer.writerow(
            {
                "User Name": name,
                "User Email": data["User Email"],
                "Unavailability Percentage": data["Unavailability Percentage"],
                "Unavailability Minutes Daily Average": data["Unavailability Minutes Daily Average"],
                "Unavailability Minutes Total": data["Unavailability Minutes Total"],
                "Go Unavailable Daily Frequency": data["Go Unavailable Daily Frequency"],
                "Go Unavailable Total": data["Go Unavailable Total"],
            }
        )
