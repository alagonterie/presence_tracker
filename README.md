# Presence Tracker

Tracks Microsoft Teams presence status for specified users within defined time windows and generates reports and visual timelines.

## Features

*   Tracks user presence (Availability: Available, Away, Offline, etc.) using Microsoft Graph API.
*   Logs periods of unavailability (Away, Offline) to a SQLite database (`presence_tracker.db`).
*   Configurable tracking schedule (start/end hours) and polling interval via `params.json`.
*   Stores user information (ID, email, display name, job title).
*   Provides optional notifications via Gotify for session start/end and significant unavailability periods.
*   Generates CSV reports summarizing user unavailability (`generate_report.py`).
*   Generates PDF visual timelines of user availability per session (`generate_timeline.py`).

## Prerequisites

*   Python 3.x
*   Azure AD Application Registration:
    *   An Azure AD application with the `Presence.Read` permission granted (delegated).
    *   Your Azure Client ID.
*   (Optional) Gotify server URL and application tokens for notifications.

## Installation

1.  **Clone the repository (or download the files).**
2.  **Install dependencies:**
    ```bash
    pip install -r requirements.txt
    ```

## Configuration

Modify the `params.json` file to configure the tracker:

*   `gotify_url`: (Optional) URL of your Gotify server.
*   `gotify_app_tokens`: (Optional) List of Gotify application tokens for sending notifications.
*   `authority`: (Optional) Microsoft login authority URL (default is usually fine).
*   `azure_client_id`: **Required.** Your Azure AD application's Client ID.
*   `login_username`: (Optional) The username (email) to pre-fill during the interactive login flow.
*   `ping_seconds`: Interval (in seconds) for checking presence status.
*   `start_hour`: Hour (24-hour format) to start tracking (e.g., 9 for 9 AM).
*   `end_hour`: Hour (24-hour format) to stop tracking (e.g., 17 for 5 PM).
*   `tracked_user_emails`: **Required.** List of user emails to track.
    *   Prefix emails with `+` characters to increase notification/logging severity (up to `+++`).
*   `report_days`: Number of past days to include in reports/timelines (used by generation scripts).

## Usage

1.  **Run the tracker:**
    ```bash
    python main.py [optional_path_to_params.json]
    ```
    *   The first time you run it, you will be prompted to log in via a browser to grant the application permission. Subsequent runs may use cached credentials.
    *   The script will run between the configured `start_hour` and `end_hour`.
    *   Presence data is logged to `presence_tracker.db`.
    *   Logs are stored in the `logs/` directory.

2.  **Generate Reports:**
    ```bash
    python generate_report.py
    ```
    *   Reads data from `presence_tracker.db`.
    *   Uses the `report_days` parameter from `params.json`.
    *   Creates a CSV file in the `reports/` directory (e.g., `YYYY-MM-DD-YYYY-MM-DD_presence_report.csv`).

3.  **Generate Timelines:**
    ```bash
    python generate_timeline.py
    ```
    *   Reads data from `presence_tracker.db`.
    *   Uses the `report_days` parameter from `params.json`.
    *   Creates a multi-page PDF file in the `timelines/` directory (e.g., `YYYY-MM-DD_to_YYYY-MM-DD_visual_timeline.pdf`), with each page representing a tracking session.

## Database Schema (`presence_tracker.db`)

*   **user**: Stores information about tracked users.
    *   `id`: Microsoft Graph User ID (Primary Key)
    *   `mail`: User email
    *   `display_name`: User display name
    *   `job_title`: User job title
*   **session**: Represents a single run of the `main.py` script.
    *   `id`: Auto-incrementing session ID (Primary Key)
    *   `start_time`: Timestamp when the session started
    *   `end_time`: Timestamp when the session ended
*   **presence**: Records periods when a user was *not* available (e.g., Away, Offline).
    *   `id`: Auto-incrementing presence record ID (Primary Key)
    *   `session_id`: Foreign key linking to the `session` table
    *   `user_id`: Foreign key linking to the `user` table
    *   `start_time`: Timestamp when the unavailability started
    *   `end_time`: Timestamp when the unavailability ended (or when the session ended if still unavailable)
    *   `duration_seconds`: Calculated duration of the unavailability period in seconds

## Dependencies

See `requirements.txt`. 