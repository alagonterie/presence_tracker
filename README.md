# Presence Tracker

## Overview

**Presence Tracker** is a Python-based tool designed to monitor the online presence of a predefined set of users on specific platforms (e.g., via Azure or
Microsoft Graph). It tracks user availability, logs session data, compiles usage statistics, and sends notifications or reports as necessary.

The project leverages database models, APIs, user management, and reporting/visualization to provide insights about user availability within a defined time
period. It also supports exporting tracked data into easy-to-read reports or timelines.

## Features

1. **User Tracking**

- Monitor the presence of users (tracked via email addresses).
- Logs user session start, session end, and duration of availability.

2. **Notifications**

- Sends presence notifications as sessions start/end.
- Allows configuration of notification URLs for external integrations.

3. **Database Model**

- Structured database schema to store users, sessions, and presence data using **Peewee ORM**.

4. **Customizable Parameters**

- Custom tracking hours, notification settings, user emails, and more defined in `params.json`.

5. **Reporting Tools**

- Generate detailed and customizable reports on user activity over a number of days.
- Export reports in formats such as CSV.

6. **Visualization**

- Generate timelines that visually map user sessions over time using **Matplotlib**.

## Prerequisites

To set up and run this project, ensure you have the following dependencies installed:

### Python Requirements

- Python 3.13.1 or higher

### Libraries

These are listed in `requirements.txt`:

```plaintext
azure-core~=1.32.0
azure-identity~=1.15.0
colorlog~=6.9.0
matplotlib~=3.10.0
msgraph-sdk~=1.20.0
peewee~=3.17.1
requests~=2.32.3
```

Use the following command to install requirements:

```bash
pip install -r requirements.txt
```

## Project Structure

- **`main.py`**:  
  The primary entry point to run the presence tracker application. This script manages the core runtime, initializes parameters, loads the database, and begins
  the presence tracking process.

- **`generate_report.py`**:  
  A utility script to generate CSV files summarizing user activity within a defined reporting period. It calculates total active time and periods of
  unavailability for each user.

- **`generate_timeline.py`**:  
  Generates visual timelines of user availability using **Matplotlib**. These timelines are color-coded and visually show session start, end, and other
  statistics.

- **`params.json`**:  
  Configuration file for the tracker. It contains key parameters, such as notification URL, Azure client ID, and a list of emails to track.

- **`requirements.txt`**:  
  Contains all Python libraries required to run the application.

## Usage

### 1. Configure Parameters

Edit the `params.json` file to define:

- The email addresses of tracked users.
- Notification configurations.
- Tracking hours, report intervals, etc.

Example of `params.json`:

```json
{
  "notify_url": "https://example.com/notify",
  "azure_client_id": "your-client-id",
  "login_username": "your-username@example.com",
  "end_hour": 16,
  "tracked_user_emails": ["email1@example.com", "+email2@example.com"],
  "report_days": 14
}
```

### 2. Run Presence Tracker

Start tracking user presence through:

```bash
python main.py
```

### 3. Generate Reports

Produce a report summarizing user activity over the specified period (e.g., 14 days):

```bash
python generate_report.py
```

### 4. Visualize Session Timelines

Generate a visual timeline of user sessions via:

```bash
python generate_timeline.py
```

## Key Classes and Scripts

### Core Classes

- **Params**:
    - Handles the loading and customization of tracking parameters.
    - Attributes: `notify_url`, `azure_client_id`, `tracked_user_emails`, etc.

- **DbBase and Database Models (e.g., DbUser, DbSession, DbPresence)**:
    - Define and manage the relational database structure and entities.
    - Tracks users, their sessions, and their availability.

- **Notifier**:
    - Manages the logic for sending presence and statistics notifications to the configured URL.

- **Repository**:
    - Performs database operations such as adding users, retrieving sessions, and closing incomplete records.

- **PresenceTracker**:
    - The main logic for tracking user presence asynchronously.
    - Performs actions like logging session availability and interacting with APIs.

### Utility Scripts

- **generate_report.py**:
    - Contains methods to extract database data and produce CSV reports.

- **generate_timeline.py**:
    - Provides a timeline visualization of user presence using data from the database.

## Dependencies

This project heavily relies on:

- **Azure APIs:** To fetch user presence data via `azure-identity` and `msgraph-sdk` libraries.
- **Matplotlib:** For generating visual timelines.
- **Peewee ORM:** For managing and interacting with a lightweight SQLite database.
- **Requests:** For HTTP interactions like sending notifications.

## Example Workflow

1. Configure the desired users in `params.json`.
2. Run the `main.py` script to track user availability across the defined hours.
3. Produce actionable insights by running `generate_report.py` or visualizing the logs with `generate_timeline.py`.

## Future Improvements

- Add a web-based front end to visualize reports and timelines dynamically.
- Support more platforms for presence tracking beyond Azure (e.g., Google Workspace).