from asyncio import sleep, run
from datetime import datetime, date
from json import load
from logging import basicConfig, INFO
from math import ceil, floor
from os import access, R_OK
from os.path import isfile
from sys import argv
from typing import Optional

from azure.identity import InteractiveBrowserCredential, TokenCachePersistenceOptions
from msgraph import GraphServiceClient
from msgraph.generated.communications.get_presences_by_user_id.get_presences_by_user_id_post_request_body import \
    GetPresencesByUserIdPostRequestBody
from msgraph.generated.models.presence import Presence
from msgraph.generated.models.user import User
from msgraph.generated.users.users_request_builder import UsersRequestBuilder

basicConfig(level=INFO)

_DEFAULT_PARAMS_FILE = "params.json"
_DEFAULT_AZURE_CLIENT_ID = "00000000-0000-0000-0000-000000000000"
_DEFAULT_AUTHORITY = "https://login.microsoftonline.com"
_NO_ARG = 1


class Params:
    def __init__(self, params_file_path: str = _DEFAULT_PARAMS_FILE) -> None:
        self.authority = _DEFAULT_AUTHORITY
        self.azure_client_id = _DEFAULT_AZURE_CLIENT_ID
        self.login_username = None
        self.ping_seconds = 60
        self.start_hour = 9
        self.end_hour = 15
        self.tracked_user_emails = []
        self._load_params(params_file_path)

    def _load_params(self, params_file_path: str) -> None:
        if len(argv) > _NO_ARG:
            params_file_path = argv[_NO_ARG]

        if not self._is_valid_file(params_file_path):
            exit(1)

        with open(params_file_path) as params_file:
            params_dict = load(params_file)

        self.authority = params_dict.get("authority", _DEFAULT_AUTHORITY)
        self.azure_client_id = params_dict.get("azure_client_id", _DEFAULT_AZURE_CLIENT_ID)
        self.login_username = params_dict.get("login_username", None)
        self.ping_seconds = params_dict.get("ping_seconds", 60)
        self.start_hour = params_dict.get("start_hour", 9)
        self.end_hour = params_dict.get("end_hour", 15)
        self.tracked_user_emails = params_dict.get("tracked_user_emails", [])

    @staticmethod
    def _is_valid_file(file_path: str) -> bool:
        if isfile(file_path) and access(file_path, R_OK):
            return True
        else:
            print(
                f"The provided parameters file cannot be accessed. Please make sure the file exists and is readable. "
                f"Default expected: (dir_containing_python_script)/{_DEFAULT_PARAMS_FILE}"
            )
            return False


class PresenceTracker:
    def __init__(self) -> None:
        self.params = Params()
        self.graph_client = self._initialize_graph_client(self.params)
        self.users: dict[str, User] = {}
        self.tracking_start_time: Optional[datetime] = None
        self.user_away_minutes: dict[str, float] = {}
        self.user_unavailable_start_times: dict[str, Optional[datetime]] = {}
        self.user_unavailable_timespans: dict[str, list[tuple[datetime, datetime]]] = {}

    async def track(self) -> None:
        await self._populate_tracked_users_async()

        start_dt, end_dt = self._get_start_and_end_time()

        if datetime.now() < start_dt:
            print(f"Waiting until the scheduled start time: {self._format_time(start_dt)}...")

            while datetime.now() < start_dt:
                await sleep(1)

        await self._track_during_scheduled_time(end_dt)

        self._end_of_scheduled_time_cleanup(end_dt)
        self._print_presence_statistics(end_dt, start_dt)

    async def _track_during_scheduled_time(self, end_dt: datetime) -> None:
        while datetime.now() < end_dt:
            await self._track_user_presence_async()
            await sleep(self.params.ping_seconds)

    async def _populate_tracked_users_async(self) -> None:
        email_chunks = self._chunk_emails(self.params.tracked_user_emails)
        for chunk in email_chunks:
            query_params = UsersRequestBuilder.UsersRequestBuilderGetQueryParameters(
                select=["id", "displayName", "jobTitle"],
                filter=f"mail in ({', '.join([f'\'{email}\'' for email in chunk])})",
            )

            request_config = UsersRequestBuilder.UsersRequestBuilderGetRequestConfiguration(
                query_parameters=query_params
            )
            response = await self.graph_client.users.get(request_configuration=request_config)

            self.users.update({user.id: user for user in response.value})

        for user in self.users.values():
            self.user_away_minutes[user.display_name] = 0

    async def _track_user_presence_async(self) -> None:
        if self.tracking_start_time is None:
            self.tracking_start_time = datetime.now()

        request_body = GetPresencesByUserIdPostRequestBody(ids=[user_id for user_id in self.users.keys()])
        response = await self.graph_client.communications.get_presences_by_user_id.post(request_body)

        for presence in response.value:
            self._track_individual_user(presence)

        self.tracking_start_time = datetime.now()

    def _track_individual_user(self, presence: Presence) -> None:
        display_name, availability, user_id = self.users[presence.id].display_name, presence.availability, presence.id
        dt_now = datetime.now()

        if availability in ['Away', 'Offline']:
            dt_start = self.user_unavailable_start_times.get(user_id)

            if dt_start is None:
                self.user_unavailable_start_times[user_id] = dt_now
                print(f"{display_name} went {availability.lower()} at {self._format_time(dt_now)}")
        else:
            self._handle_user_availability(dt_now, user_id)

    def _handle_user_availability(self, dt_now: datetime, user_id: str) -> None:
        dt_start = self.user_unavailable_start_times.get(user_id)

        if dt_start is not None:
            self._store_unavailability(user_id, dt_start, dt_now)

    def _store_unavailability(self, user_id: str, dt_start: datetime, dt_now: datetime) -> None:
        str_start, str_now = self._format_time(dt_start), self._format_time(dt_now)
        display_name = self.users[user_id].display_name

        if str_start != str_now:
            print(f"{display_name} was unavailable from {str_start} to {str_now}")

        if display_name not in self.user_unavailable_timespans:
            self.user_unavailable_timespans[display_name] = []

        self.user_unavailable_timespans[display_name].append((dt_start, dt_now))
        self.user_unavailable_start_times[user_id] = None

        duration_minutes = (dt_now - dt_start).total_seconds() / 60
        self.user_away_minutes[display_name] = round(self.user_away_minutes.get(display_name, 0) + duration_minutes, 2)

    def _end_of_scheduled_time_cleanup(self, end_dt: datetime) -> None:
        for user_id, user_start_dt in self.user_unavailable_start_times.items():
            if user_start_dt is not None:
                self._end_of_day_cleanup_for_unavailable_user(user_id, user_start_dt, end_dt)

    def _end_of_day_cleanup_for_unavailable_user(self, user_id: str, user_start_dt: datetime, end_dt: datetime) -> None:
        display_name = self.users[user_id].display_name

        print(f"{display_name} was unavailable from {self._format_time(user_start_dt)} to {self._format_time(end_dt)}")

        if display_name not in self.user_unavailable_timespans:
            self.user_unavailable_timespans[display_name] = []

        self.user_unavailable_timespans[display_name].append((user_start_dt, end_dt))

        duration_minutes = (end_dt - user_start_dt).total_seconds() / 60
        self.user_away_minutes[display_name] = round(self.user_away_minutes.get(display_name, 0) + duration_minutes, 2)

    # noinspection PyMethodMayBeStatic
    def _get_start_and_end_time(self) -> tuple[datetime, datetime]:
        # from datetime import time  # real
        # start_time = time(self.params.start_hour, 0)  # real time
        # end_time = time(self.params.end_hour, 0)  # real time

        from datetime import timedelta  # test
        start_time = (datetime.now() + timedelta(seconds=10)).time()  # test time
        end_time = (datetime.now() + timedelta(seconds=10, minutes=2)).time()  # test time

        start_dt = datetime.combine(date.today(), start_time)
        end_dt = datetime.combine(date.today(), end_time)
        return start_dt, end_dt

    def _print_presence_statistics(self, end_dt: datetime, start_dt: datetime) -> None:
        print(f"Presence stats from {self._format_time(start_dt)} to {self._format_time(end_dt)}:")
        for user in sorted(
            [
                user for user in self.user_away_minutes.keys()
                if ceil(self.user_away_minutes[user]) < floor((end_dt - start_dt).total_seconds() / 60)
            ], key=lambda x: self.user_away_minutes[x], reverse=True
        ):
            print(f"{user} was unavailable for a total of {self.user_away_minutes[user]} minute(s)")

    @staticmethod
    def _initialize_graph_client(params: Params) -> GraphServiceClient:
        # noinspection PyTypeChecker
        return GraphServiceClient(
            credentials=InteractiveBrowserCredential(
                client_id=params.azure_client_id,
                authority=params.authority,
                login_hint=params.login_username,
                cache_persistence_options=TokenCachePersistenceOptions()
            ),
            scopes=["Presence.Read"]
        )

    @staticmethod
    def _chunk_emails(emails: list[str]) -> list[list[str]]:
        email_chunk_limit = 15
        chunks = [emails[i:i + email_chunk_limit] for i in range(0, len(emails), email_chunk_limit)]
        return chunks

    @staticmethod
    def _format_time(dt: datetime) -> str:
        return dt.strftime('%I:%M%p').lstrip('0').lower()


def main() -> None:
    run(PresenceTracker().track())


if __name__ == '__main__':
    main()
