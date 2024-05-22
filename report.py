import json
import sqlite3
import csv
from collections import defaultdict
from datetime import datetime, timedelta, date

# Load parameters from JSON file
with open('params.json') as f:
    params = json.load(f)

# Get the number of days from params
report_days = params.get('report_days', 30)
if report_days < 1:
    report_days = 1


# Convert seconds to minutes and round it off
def seconds_to_minutes(seconds):
    return round(seconds / 60)


# Connect to the SQLite DB
conn = sqlite3.connect('presence_tracker.db')
cursor = conn.cursor()

# Calculate start date report_days ago
date_report_days_ago = datetime.now() - timedelta(days=report_days)

# Count the number of days with sessions, excluding weekends
cursor.execute(
    """
    SELECT DISTINCT DATE(start_time) AS session_day
    FROM SESSION
    WHERE start_time >= ?
    """, (date_report_days_ago,)
)
session_days = sum(1 for row in cursor.fetchall() if date.fromisoformat(row[0]).weekday() < 5)

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
for user_id, count, duration in cursor.fetchall():
    # Get user email
    cursor.execute("SELECT mail FROM user WHERE id = ?", (user_id,))
    user_email = cursor.fetchone()[0]
    user_presence[user_email]["total_availability_changes"] = count
    user_presence[user_email]["total_unavailability_minutes"] = seconds_to_minutes(duration)
    user_presence[user_email]["average_unavailability_minutes_per_session"] = seconds_to_minutes(duration / session_days)
    user_presence[user_email]["frequency_to_unavailable_per_session"] = count / session_days

# Close the db connection
cursor.close()
conn.close()

fields = [
    "email",
    "total_availability_changes",
    "total_unavailability_minutes",
    "average_unavailability_minutes_per_session",
    "frequency_to_unavailable_per_session"
]

# Sort the result based on average_unavailability_minutes_per_session in descending order
sorted_user_presence = dict(sorted(user_presence.items(), key=lambda item: item[1]['average_unavailability_minutes_per_session'], reverse=True))

# Write the result to a CSV file
with open('report.csv', 'w', newline='') as f:
    writer = csv.DictWriter(f, fieldnames=fields)
    writer.writeheader()
    for email, data in sorted_user_presence.items():
        writer.writerow(
            {
                "email": email,
                "total_availability_changes": data["total_availability_changes"],
                "total_unavailability_minutes": data["total_unavailability_minutes"],
                "average_unavailability_minutes_per_session": data["average_unavailability_minutes_per_session"],
                "frequency_to_unavailable_per_session": data["frequency_to_unavailable_per_session"],
            }
        )
