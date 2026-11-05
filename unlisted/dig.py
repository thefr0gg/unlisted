import os
import re
import json
import random
import signal
import string
import requests
import threading

from pyt import Client, ChannelFeed
from user_agent import generate_user_agent

from unlisted import constants

from unlisted import messages

_CHARS = string.ascii_letters + string.digits + '-_'

# An 11-char ID encodes 64 bits (10*6 + 4), so the last char only ever takes
# 16 values: those whose low two bits are zero.
_LAST_CHARS = ''.join(c for i, c in enumerate(string.ascii_uppercase + string.ascii_lowercase + string.digits + '-_') if i % 4 == 0)

class Dig(object):
    """ Unlisted videos digger """

    def __init__(self, channel_identifier: str, channel_url: str, threads: int | None = 3, delay: float = 0.5, output_file_path: str | None = None, is_open_search: bool | None = False) -> None:
        self.channel_identifier = channel_identifier
        self.channel_url = channel_url
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
        self.checked: int = 0
        self.rate_limited: int = 0

        self._state_lock = threading.Lock()
        self._data_lock = threading.Lock()
        self._save_lock = threading.Lock()

        self.running_threads: list = []
        self.exit_flag = threading.Event()

    def load_previous(self, data: dict) -> None:
        """ Restores state from a previous result file """
        self.used_videos_uid = list(data["used_videos_uid"])
        self._used_set = set(self.used_videos_uid)
        self.unlisted_videos_data = list(data["unlisted_videos_data"])

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
                timeout=10,
            )
        except requests.RequestException:
            return False

        return response.status_code == 200

    def start(self, console_log) -> None:
        """ Starts the `dig` function in multipule threads """
        if not self.is_open_search:
            channel = Client().channel(self.channel_url)

            pub_list = self._fetch_public_videos(channel=channel)
            self.public_videos_uid = frozenset(pub_list)

            with self._state_lock:
                for uid in pub_list:
                    if uid not in self._used_set:
                        self._used_set.add(uid)
                        self.used_videos_uid.append(uid)

            self.channel_name = self._channel_author(channel=channel)

        # Rebuild the "found" set from a resumed result file.
        for entry in self.unlisted_videos_data:
            if self.is_open_search or entry.get("channel_name") == self.channel_name:
                self.unlisted_videos.add(entry["video_uid"])

        signal.signal(signal.SIGINT, self._signal_handler)

        self._initiate_file_output()

        save_thread = threading.Thread(target=self._periodic_save_loop, daemon=True)
        save_thread.start()

        for thread_index in range(self.threads):
            thread = threading.Thread(
                target=self.dig,
                args=(console_log, thread_index),
                daemon=True,
            )
            thread.start()
            self.running_threads.append(thread)

    def dig(self, console_log, thread_index: int) -> None:
        """ Digs all the unlisted videos in a channel """
        url = "https://youtube.com/watch?v="
        backoff = 1.0

        while not self.exit_flag.is_set():
            video_uid = self._generate_video_uid()
            video_url = f"{url}{video_uid}"

            headers = {"User-Agent": generate_user_agent()}

            try:
                response = requests.get(
                    f"https://www.youtube.com/oembed?url={video_url}&format=json",
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

                with self._state_lock:
                    self.checked += 1

                if response.status_code == 200:
                    oembed = response.json()
                    video_title = oembed.get("title", "")
                    video_author = oembed.get("author_name", "")

                    video_data = {
                        "video_uid": video_uid,
                        "video_url": video_url,
                        "video_title": video_title,
                        "channel_name": video_author,
                    }

                    if self.channel_name is not None:
                        if video_author == self.channel_name:
                            console_log(messages.FOUND_UNLISTED_VIDEO_FOR_CURRENT_CHANNEL(video_url=video_url, channel_name=self.channel_name, thread_index=thread_index))
                            with self._state_lock:
                                self.unlisted_videos.add(video_uid)
                        else:
                            console_log(messages.FOUND_UNLISTED_VIDEO_FOR_OTHER_CHANNEL(video_url=video_url, channel_name=video_author, thread_index=thread_index))
                    elif self.is_open_search:
                        console_log(messages.FOUND_UNLISTED_VIDEO_FOR_OTHER_CHANNEL(video_url=video_url, channel_name=video_author, thread_index=thread_index))
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

    def _fetch_public_videos(self, channel: ChannelFeed) -> list[str]:
        """ Fetchs the channel's public videos urls """
        videos_uid = []
        public_videos_urls = channel.video_urls

        for video_url in public_videos_urls:
            video_uid = video_url.split("=")[-1]
            videos_uid.append(video_uid)

        return videos_uid

    def _signal_handler(self, sig, frame):
        self.exit_flag.set()

    def stop(self) -> None:
        """ Stops the workers, waits for in-flight requests, then saves """
        self.exit_flag.set()

        for thread in self.running_threads:
            thread.join(timeout=10)

        self._save_results()

    def _channel_author(self, channel: ChannelFeed) -> str:
        """ Gets the channel author """
        return channel.name

    def _generate_video_uid(self) -> str:
        """ Generates a random 11-character video UID """
        while True:
            candidate = ''.join(random.choices(_CHARS, k=10)) + random.choice(_LAST_CHARS)
            with self._state_lock:
                if candidate not in self._used_set:
                    return candidate

    def _periodic_save_loop(self) -> None:
        while not self.exit_flag.wait(timeout=30):
            self._save_results()

    def _initiate_file_output(self) -> None:
        """ Resolves the output file path and writes the initial state """
        if not os.path.isfile(self.output_file_path):
            suffix = self.channel_name if self.channel_name is not None else random.randint(100000, 999999)
            suffix = re.sub(r"[^\w.-]", "_", str(suffix))
            filename = f"unlisted-dig-results-{suffix}.json"
            self.output_file_path = os.path.join(self.output_file_path, filename)

        self._save_results()

    def _save_results(self) -> None:
        """ Saves the results into the `self.output_file_path` """
        with self._save_lock:
            with self._data_lock:
                snapshot_data = list(self.unlisted_videos_data)

            with self._state_lock:
                snapshot_used_uids = list(self.used_videos_uid)

            output_file_data = dict(constants.UNLISTED_VIDEOS_DATA)
            if not self.is_open_search:
                output_file_data["channel_name"] = self.channel_name

            output_file_data["unlisted_videos_data"] = snapshot_data
            output_file_data["used_videos_uid"] = snapshot_used_uids

            tmp_path = f"{self.output_file_path}.tmp"
            with open(tmp_path, "w", encoding="utf-8") as f:
                f.write(json.dumps(output_file_data, indent=4, ensure_ascii=False))
            os.replace(tmp_path, self.output_file_path)
