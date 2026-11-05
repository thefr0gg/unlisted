import os
import sys
import json
import time
import argparse

from queue import Queue, Empty

from rich import print
from rich.console import Console
from rich.table import Table

from unlisted import constants

# Messages
from unlisted import messages

# Dig
from unlisted.dig import Dig

# Utils
from unlisted.utils import (
    is_url,
    channel_url
)


def _format_elapsed(elapsed: float) -> str:
    h = int(elapsed) // 3600
    m = (int(elapsed) % 3600) // 60
    s = int(elapsed) % 60
    return f"{h:02d}:{m:02d}:{s:02d}"


def _print_summary(console: Console, dig: Dig, elapsed: float) -> None:
    table = Table.grid(padding=(0, 2))
    table.add_column(style="dim", justify="right")
    table.add_column(justify="right")

    table.add_row("found",   f"[bold green]{len(dig.unlisted_videos):,}[/]")
    table.add_row("checked", f"[bold yellow]{dig.checked:,}[/]")
    table.add_row("failed",  f"[bold red]{dig.faild_attempts:,}[/]")
    table.add_row("blocked", f"[dim]{dig.rate_limited:,}[/]")
    table.add_row("elapsed", f"[dim]{_format_elapsed(elapsed)}[/]")

    console.print()
    console.print(table)


def _positive_int(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return number


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="unlisted")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("version", help="Unlisted's current version")

    dig_parser = subparsers.add_parser(
        "dig",
        help="Digs a channel's unlisted videos, or it can be set to open to dig for all channels",
    )
    dig_parser.add_argument(
        "--channel-identifier", dest="channel_identifier", default=None,
        help="Channel handle to target",
    )
    dig_parser.add_argument(
        "--open", dest="open_search", action="store_true",
        help="Dig unlisted videos for all channels",
    )
    dig_parser.add_argument(
        "--threads", type=_positive_int, default=3, help="Threads to use",
    )
    dig_parser.add_argument(
        "--delay", type=int, default=500,
        help="Delay between requests per thread in milliseconds",
    )
    dig_parser.add_argument(
        "--output", dest="output_file_path", default="./",
        help="Path to a file to save the results in",
    )
    dig_parser.add_argument(
        "--ignore-uids-from-result", dest="ignore_uids_from_result", default=None,
        help="Ignore used videos UIDs from a result file",
    )

    return parser


def version() -> None:
    """ Unlisted's current version """
    print(f"Version [bold cyan]{constants.VERSION}[bold white]")

def dig(
    channel_identifier: str = None,
    open_search: bool = False,
    threads: int = 3,
    delay: int = 500,
    output_file_path: str = "./",
    ignore_uids_from_result: str = None,
) -> None:
    """
    Digs a channel's unlisted videos, or it can be set to open to dig for all channels
    """
    console = Console()
    console._log_render.omit_repeated_times = False

    current_channel_url = None

    if channel_identifier is None and not open_search:
        console.log(messages.CHANNEL_IDENTIFIER_REQUIRED)
        sys.exit(1)

    if channel_identifier is not None:
        if is_url(text=channel_identifier):
            console.log(messages.CHANNEL_IDENTIFIER_SHOULD_NOT_BE_A_URL)
            sys.exit(1)

        channel_identifier = channel_identifier.lstrip("@")
        current_channel_url = channel_url(channel_name=channel_identifier)

    if not os.path.exists(output_file_path):
        console.log(messages.OUTPUT_FILE_PATH_NOT_FOUND)
        sys.exit(1)

    data = None

    if ignore_uids_from_result is not None:
        if not os.path.isfile(ignore_uids_from_result) or not os.path.exists(ignore_uids_from_result):
            console.log(messages.RESULT_FILE_PATH_NOT_FOUND)
            sys.exit(1)

        with open(ignore_uids_from_result, "r") as result_file:
            data = json.load(result_file)

    regular_result_keys = [
        "package",
        "version",
        "author",
        "channel_name",
        "unlisted_videos_data",
        "used_videos_uid"
    ]

    for key in regular_result_keys:
        if data is not None and key not in data.keys():
            console.log(messages.RESULT_FILE_IS_CORRUPTED)
            sys.exit(1)

    console_log_msgs = Queue()

    def console_log(log_msg: str):
        console_log_msgs.put(log_msg)

    dig_obj = Dig(
        channel_identifier=channel_identifier,
        channel_url=current_channel_url,
        threads=threads,
        delay=delay / 1000,
        output_file_path=output_file_path,
        is_open_search=open_search,
    )

    if data is not None:
        dig_obj.load_previous(data)

    if current_channel_url is not None:
        console.log(messages.CHECKING_CHANNEL_URL(channel_url=current_channel_url))

        if not dig_obj.check_channel_url():
            console.log(messages.CHANNEL_URL_IS_NOT_VALID(channel_url=current_channel_url))
            sys.exit(1)

    if not open_search:
        mode_line = f"[white]digging[/]  [bold green]{channel_identifier}[/]  [dim]|[/]  {threads} thread{'s' if threads != 1 else ''}"
    else:
        mode_line = f"[white]digging[/]  [bold green]all channels[/]  [dim]|[/]  {threads} thread{'s' if threads != 1 else ''}"

    console.print(mode_line)

    dig_obj.start(console_log=console_log)

    # --- streaming output ---
    start_time = time.time()

    try:
        while not dig_obj.exit_flag.is_set():
            try:
                console.log(console_log_msgs.get(timeout=0.2))
            except Empty:
                continue
    except KeyboardInterrupt:
        dig_obj.exit_flag.set()

    console.log("stopping workers and saving results...")
    dig_obj.stop()

    # drain any remaining log messages
    while True:
        try:
            console.log(console_log_msgs.get_nowait())
        except Empty:
            break

    _print_summary(console, dig_obj, time.time() - start_time)
    console.log(f"[bold green][ ! ] [bold white]results saved to [bold yellow]'{dig_obj.output_file_path}'[/]")

def run():
    """ Runs Unlisted """
    constants.banner()

    parser = _build_parser()
    args = parser.parse_args()

    if args.command == "version":
        version()
    elif args.command == "dig":
        dig(
            channel_identifier=args.channel_identifier,
            open_search=args.open_search,
            threads=args.threads,
            delay=args.delay,
            output_file_path=args.output_file_path,
            ignore_uids_from_result=args.ignore_uids_from_result,
        )

if __name__ == "__main__":
    run()
