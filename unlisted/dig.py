import os
import re
import json
import random
import signal
import string
import time
import requests
import threading

from pyt.legacy import Channel
from user_agent import generate_user_agent

from unlisted import constants

from unlisted.proxy_handler import ProxyHandler
from unlisted.log_msgs import info
from unlisted.thread_task import ThreadTask

_CHARS = string.ascii_letters + string.digits + '-'

class Dig(object):
    """ Unlisted videos digger """

    def __init__(self, channel_identifier: str, channel_url: str, proxy_handler: ProxyHandler, threads: int | None = 3, delay: float = 0.5, output_file_path: str | None = None, is_open_search: bool | None = False) -> None:
        self.channel_identifier = channel_identifier
        self.channel_url = channel_url
        self.proxy_handler = proxy_handler
        self.threads = threads
        self.delay = delay
        self.output_file_path = output_file_path
        self.is_open_search = is_open_search

        self.public_videos_uid: frozenset = frozenset()
        self._used_set: set = set()
        self.used_videos_uid: list = []
        self.unlisted_videos: set = set()
        self.unlisted_videos_data: list = []
        self.channel_name: str | None = None
        self.faild_attempts: int = 0
        self.rate_limited: int = 0

        self._state_lock = threading.Lock()
        self._data_lock = threading.Lock()
        self._save_lock = threading.Lock()

        self.running_threads: list = []
        self.exit_flag = threading.Event()

    def check_channel_url(self) -> bool:
        """ Checks if the `channel_url` exists """
        url_regex = r'\bhttps?://(?:www\.)?youtube\.com/(?:c/|user/|channel/|@)([a-zA-Z0-9_-]+)\b'

        urls = re.findall(url_regex, self.channel_url)

        if len(urls) != 1:
            return False

        headers = {"User-Agent": generate_user_agent()}

        try:
            response = requests.get(
                self.channel_url,
                headers=headers,
                proxies=self.proxy_handler.get_random_proxy(),
                timeout=8,
            )
            if response.status_code == 200:
                return True
        except requests.RequestException:
            pass

        # Public proxies are unreliable, so fall back to a direct request.
        try:
            response = requests.get(self.channel_url, headers=headers, timeout=10)
        except requests.RequestException:
            return False

        return response.status_code == 200

    def _load_channel(self) -> Channel:
        """ Loads the channel, retrying on transient network errors """
        last_error = None

        for _ in range(3):
            try:
                channel = Channel(self.channel_url)
                self.channel_name = self._channel_author(channel=channel)
                return channel
            except Exception as error:
                last_error = error
                time.sleep(1)

        raise last_error

    def start(self, console_log) -> None:
        """ Starts the `dig` function in multipule threads """
        if not self.is_open_search:
            channel = self._load_channel()

            try:
                pub_list = self._fetch_public_videos(channel=channel)
            except Exception:
                # The public list is only used to skip already-public videos.
                # A truncated response here should not abort the dig.
                pub_list = []

            self.public_videos_uid = frozenset(pub_list)
            self._used_set.update(pub_list)

        signal.signal(signal.SIGINT, self._signal_handler)

        self._initiate_file_output()

        save_thread = threading.Thread(target=self._periodic_save_loop, daemon=True)
        save_thread.start()

        for _ in range(self.threads):
            thread_task = ThreadTask(
                target_function=self.dig,
                args=(console_log, _)
            )
            thread_task.start()
            self.running_threads.append(thread_task)

    def dig(self, console_log, thread_index: int) -> None:
        """ Digs all the unlisted videos in a channel """
        url = "https://youtube.com/watch?v="
        backoff = 1.0

        while not self.exit_flag.is_set():
            video_uid = self._generate_video_uid()
            video_url = f"{url}{video_uid}"

            proxies = self.proxy_handler.get_random_proxy()
            headers = {"User-Agent": generate_user_agent()}

            try:
                response = requests.get(
                    f"https://www.youtube.com/oembed?url={video_url}&format=json",
                    proxies=proxies,
                    headers=headers,
                    timeout=8,
                )

                if response.status_code == 429:
                    with self._state_lock:
                        self.rate_limited += 1
                    self.exit_flag.wait(timeout=backoff)
                    backoff = min(backoff * 2, 60.0)
                    continue

                backoff = 1.0

                if response.status_code == 200:
                    oembed = response.json()
                    video_title = oembed.get("title", "")
                    video_author = oembed.get("author_name", "")

                    video_data = {
                        "video_uid": video_uid,
                        "video_url": video_url,
                        "video_title": video_title,
                    }

                    if self.channel_name is not None:
                        if video_author == self.channel_name:
                            console_log(info.FOUND_UNLISTED_VIDEO_FOR_CURRENT_CHANNEL(video_url=video_url, channel_name=self.channel_name, thread_index=thread_index))
                            with self._state_lock:
                                self.unlisted_videos.add(video_uid)
                        else:
                            console_log(info.FOUND_UNLISTED_VIDEO_FOR_OTHER_CHANNEL(video_url=video_url, channel_name=self.channel_name, thread_index=thread_index))
                    elif self.is_open_search:
                        video_data["channel_name"] = video_author
                        console_log(info.FOUND_UNLISTED_VIDEO_FOR_OTHER_CHANNEL(video_url=video_url, channel_name=video_author, thread_index=thread_index))
                        with self._state_lock:
                            self.unlisted_videos.add(video_uid)

                    with self._data_lock:
                        self.unlisted_videos_data.append(video_data)
                else:
                    with self._state_lock:
                        self.faild_attempts += 1

            except (requests.RequestException, ValueError):
                with self._state_lock:
                    self.faild_attempts += 1

            if self.delay > 0:
                self.exit_flag.wait(timeout=self.delay)

    def _fetch_public_videos(self, channel: Channel) -> list[str]:
        """ Fetchs the channel's public videos urls """
        videos_uid = []
        public_videos_urls = channel.video_urls

        for video_url in public_videos_urls:
            video_uid = video_url.split("=")[-1]
            videos_uid.append(video_uid)

        return videos_uid

    def _signal_handler(self, sig, frame):
        self.exit_flag.set()
        self._save_results()

    def _channel_author(self, channel: Channel) -> str:
        """ Gets the channel author """
        return channel.channel_name

    def _generate_video_uid(self) -> str:
        """ Generates a random 11-character video UID """
        while True:
            candidate = ''.join(random.choices(_CHARS, k=11))
            with self._state_lock:
                if candidate not in self._used_set:
                    self._used_set.add(candidate)
                    self.used_videos_uid.append(candidate)
                    return candidate

    def _periodic_save_loop(self) -> None:
        while not self.exit_flag.wait(timeout=30):
            self._save_results()

    def _initiate_file_output(self) -> None:
        """ Save the primary template into an output file """
        data = dict(constants.UNLISTED_VIDEOS_DATA)

        if not self.is_open_search:
            data["channel_name"] = self.channel_name

        if os.path.isfile(self.output_file_path):
            pass
        elif self.output_file_path == "./":
            self.output_file_path = f"./unlisted-dig-results-{self.channel_name if self.channel_name is not None else random.choice([i for i in range(100000, 1000000)])}.json"
        else:
            if self.output_file_path.split("/")[-1] == "":
                self.output_file_path = "/".join(
                    self.output_file_path.split("/")[:-1]
                    ) + f"/unlisted-dig-results-{self.channel_name if self.channel_name is not None else random.choice([i for i in range(100000, 1000000)])}.json"
            else:
                self.output_file_path = "/".join(
                    self.output_file_path.split("/")
                    ) + f"/unlisted-dig-results-{self.channel_name if self.channel_name is not None else random.choice([i for i in range(100000, 1000000)])}.json"

        with open(self.output_file_path, "w") as output_file:
            output_file.write(json.dumps(data, indent=4))

    def _save_results(self) -> None:
        """ Saves the results into the `self.output_file_path` """
        with self._save_lock:
            with self._data_lock:
                snapshot_data = list(self.unlisted_videos_data)

            try:
                with open(self.output_file_path, "r") as f:
                    output_file_data = json.load(f)
            except (OSError, json.JSONDecodeError):
                output_file_data = dict(constants.UNLISTED_VIDEOS_DATA)
                if not self.is_open_search:
                    output_file_data["channel_name"] = self.channel_name

            output_file_data["unlisted_videos_data"] = snapshot_data
            output_file_data["used_videos_uid"] = []

            with open(self.output_file_path, "w") as f:
                f.write(json.dumps(output_file_data, indent=4))
