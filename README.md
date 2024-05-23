# Presence Tracker

## Description

A simple Python-based application designed to track the presence of specified users over Microsoft Graph API. It authenticates via Azure Active Directory, and it has
specific use cases in tracking the availability status of users, mostly for productivity, team management, and research.

## Dependencies

This application is written in `Python 3.12.2` and uses the following libraries/packages:

- `azure.identity`
- `msgraph`
- `peewee`
- `colorlog`

Please make sure to have installed the correct version of each dependency to avoid any errors.

## Configuration

In the `params.json` file, you can specify the configuration details like **authority**, **azure_client_id**, **login_username**, **ping_seconds**, **start_hour**, **end_hour**,
and a list of **tracked_user_emails**.
The format should be like this:

```json
{
  "authority": "<authority>",
  "azure_client_id": "<azure_client_id>",
  "login_username": "<login_username>",
  "ping_seconds": <ping_seconds>,
  "start_hour": <start_hour>,
  "end_hour": <end_hour>,
  "tracked_user_emails": [<tracked_user_emails>]
}
```

## Configuration Parameters

In the `params.json` file, you can specify the following configuration details:

- `authority` - (string) This is the authority host URL. It should be in format: `https://login.microsoftonline.com`.

- `azure_client_id` - (string) This is the Azure Client ID provided by your Azure Active Directory. It is a unique identifier that is used to identify an Azure Active Directory
  application.

- `login_username` - (string) The username used for login. This should be an email address associated with the `azure_client_id` provided.

- `ping_seconds` - (number) This is the frequency (in seconds) of updating user presence, a lower number means more frequent updates.

- `start_hour` - (number) This sets the time (hour in 24h format) when the tracker should start tracking. For example, setting it to `9` will start the tracker at `9AM`.

- `end_hour` - (number) This sets the end hour in 24h format. This serves as the cut-off for the tracker. For example, setting it to `17` means the tracker will stop at `5PM`.

- `tracked_user_emails` - (array of strings) This is a list of email addresses for the users you want to track. An example can
  be: ` ["user1@example.com", "user2@example.com", "user3@example.com"]`.

- `report_days` - (number) This controls the span of time considered when running `generate_report.py`. For example, setting it to `365` results in a report of the last 365 days of tracking activity.

Example `params.json`:

```json
{
  "authority": "https://login.microsoftonline.com",
  "azure_client_id": "your_azure_client_id",
  "login_username": "your_username@example.com",
  "ping_seconds": 60,
  "start_hour": 9,
  "end_hour": 17,
  "tracked_user_emails": [
    "user1@example.com",
    "user2@example.com",
    "user3@example.com"
  ],
  "report_days": 365
}
```

_**Note:** Please make sure to replace placeholders with actual values in the given example._

_**Note:** All parameters should be filled out according to user requirements and guidelines provided by Microsoft Graph API and Azure Active Directory._

## Privacy Note

Remember, you should have users' consent to track their presence. Respect privacy and use the data responsibly.

## Database Setup

The application supports SQLite and the database file is named `presence_tracker.db`. The setup will be done automatically when the application is executed. It will create three
tables:

- User
- Session
- Presence

## Usage

To use the application:

1. Update the `params.json` with your own configuration.
2. Run the python file `main.py`.

```bash
python main.py
```

## Output

Presence status updates will be displayed in the terminal.

Logs are written to `logs/`. 

Presence data from each tracking session is saved to the `presence_tracker.db` SQLite database for further querying.

# Generate Report Tool

In addition to presence tracking, the project now includes a tool for generating reports based on the recorded data. The Report Generator is a Python script
named `generate_report.py` that creates a CSV file with presence information for all tracked users.

## Configuration

`generate_report.py` reads a file named `params.json` for its configuration. The only parameter specifically required by `generate_report.py` is `report_days`. `report_days`
represents the number of days in the past to consider when generating the report. For instance, if `report_days` is set to `365`, the Report Generator will create a report
considering the last 365 days of tracking activity.

In the `params.json` file, the `report_days` field should be filled as per your requirements:

```json
{
  "report_days": 365
}
```

## Usage

To execute the report generation process, you simply need to run `generate_report.py`:

```bash
python generate_report.py
```

This will compute the statistics for the past `report_days` and generate a report as a CSV file. The file contains aggregated data from your `presence_tracker.db` SQLite DB. The more tracking sessions over time, the better the data in this report.

## Output

`generate_report.py` generates a CSV file that contains the following presence information for all tracked users:

- User Name
- User Email
- Unavailability Percentage
- Unavailability Minutes Daily Average
- Unavailability Minutes Total
- Go Unavailable Daily Frequency

## License

Please refer to the terms mentioned in the [License](https://github.com/alagonterie/presence_tracker/blob/main/LICENSE) document.

**Remember:** This application is provided as-is and should be used responsibly. Always get explicit consent from your team and/or organization before tracking their status.

## Disclaimer

The logs created by this project do not in any way connect to Microsoft Teams or any other platform and are strictly local to the system running the script.