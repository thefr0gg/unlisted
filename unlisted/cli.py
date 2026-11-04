import os
import sys
import json
import time
import socket
import typer

from queue import Queue, Empty

from rich import print
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.console import Console

from unlisted import constants

# Log messages
from unlisted.log_msgs import info, errors

# Dig
from unlisted.dig import Dig

# Proxy handler
from unlisted.proxy_handler import ProxyHandler

# Utils
from unlisted.utils import (
    is_url,
    channel_url
)

_SPINNER_FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

def _make_panel(dig: Dig, mode_line: str, elapsed: float, tick: int) -> Panel:
    spinner = _SPINNER_FRAMES[tick % len(_SPINNER_FRAMES)]
    h = int(elapsed) // 3600
    m = (int(elapsed) % 3600) // 60
    s = int(elapsed) % 60

    found   = len(dig.unlisted_videos)
    checked = len(dig.used_videos_uid)
    failed  = dig.faild_attempts
    blocked = dig.rate_limited

    table = Table.grid(padding=(0, 2))
    table.add_column(style="dim", justify="right")
    table.add_column(justify="right")

    table.add_row("found",   f"[bold green]{found:,}[/]")
    table.add_row("checked", f"[bold yellow]{checked:,}[/]")
    table.add_row("failed",  f"[bold red]{failed:,}[/]")
    table.add_row("blocked", f"[dim]{blocked:,}[/]")

    header = f"[bold cyan]{spinner}[/]  {mode_line}"
    footer = f"[dim]elapsed {h:02d}:{m:02d}:{s:02d}  ·  {dig.threads} thread{'s' if dig.threads != 1 else ''}[/]"

    grid = Table.grid(padding=(0, 0))
    grid.add_column()
    grid.add_row(header)
    grid.add_row("")
    grid.add_row(table)
    grid.add_row("")
    grid.add_row(footer)

    return Panel(grid, title="[bold]unlisted[/]", border_style="bright_black", padding=(1, 2))


# init cli
cli = typer.Typer()

@cli.command()
def version():
    """ Unlisted's current version """
    print(f"Version [bold cyan]{constants.VERSION}[bold white]")

@cli.command()
def dig(
    channel_identifier: str = None,
    open_search: bool = typer.Option(False, "--open", help="Dig unlisted videos for all channels"),
    threads: int = typer.Option(3, "--threads", help="Threads to use"),
    delay: int = typer.Option(500, "--delay", help="Delay between requests per thread in milliseconds"),
    output_file_path: str = typer.Option("./", "--output", help="Path to a file to save the results in"),
    ignore_uids_from_result: str = typer.Option(None,
    "--ignore-uids-from-result", help="Ignore used videos UIDs from a result file")
):
    """
    Digs a channel's unlisted videos, or it can be set to open to dig for all channels
    """
    console = Console()
    console._log_render.omit_repeated_times = False

    current_channel_url = None

    if channel_identifier is None and not open_search:
        console.log(errors.CHANNEL_IDENTIFIER_REQUIRED)
        sys.exit(1)

    if channel_identifier is not None:
        if is_url(text=channel_identifier):
            console.log(errors.CHANNEL_IDENTIFIER_SHOULD_NOT_BE_A_URL)
            sys.exit(1)

        current_channel_url = channel_url(channel_name=channel_identifier)

    if not os.path.exists(output_file_path):
        console.log(errors.OUTPUT_FILE_PATH_NOT_FOUND)
        sys.exit(1)

    data = None

    if ignore_uids_from_result is not None:
        if not os.path.isfile(ignore_uids_from_result) or not os.path.exists(ignore_uids_from_result):
            console.log(errors.RESULT_FILE_PATH_NOT_FOUND)
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
            console.log(errors.RESULT_FILE_IS_CORRUPTED)
            sys.exit(1)

    console_log_msgs = Queue()

    def console_log(log_msg: str):
        console_log_msgs.put(log_msg)

    # --- setup phase ---
    with console.status(info.FETCHING_AND_VALIDATING_PROXIES) as status:
        proxy_handler = ProxyHandler()
        proxy_handler.fetch()

        dig_obj = Dig(
            channel_identifier=channel_identifier,
            channel_url=current_channel_url,
            proxy_handler=proxy_handler,
            threads=threads,
            delay=delay / 1000,
            output_file_path=output_file_path,
            is_open_search=open_search,
        )

        if data is not None:
            dig_obj.used_videos_uid = list(data["used_videos_uid"])
            dig_obj._used_set = set(data["used_videos_uid"])

        if current_channel_url is not None:
            status.update(info.CHECKING_CHANNEL_URL(channel_url=current_channel_url))

            if not dig_obj.check_channel_url():
                console.log(info.CHANNEL_URL_IS_NOT_VALID(channel_url=current_channel_url))
                sys.exit(1)

        if not open_search:
            mode_line = f"[white]digging[/]  [bold green]{channel_identifier}[/]"
        else:
            mode_line = "[white]digging[/]  [bold green]all channels[/]"

        dig_obj.start(console_log=console_log)

    # --- live dashboard ---
    start_time = time.time()
    tick = 0

    with Live(console=console, refresh_per_second=10, transient=False) as live:
        while not dig_obj.exit_flag.is_set():
            while True:
                try:
                    live.console.log(console_log_msgs.get_nowait())
                except Empty:
                    break

            live.update(_make_panel(dig_obj, mode_line, time.time() - start_time, tick))
            tick += 1
            time.sleep(0.1)

        # render final state
        live.update(_make_panel(dig_obj, mode_line, time.time() - start_time, tick))

    # drain any remaining log messages
    while True:
        try:
            console.log(console_log_msgs.get_nowait())
        except Empty:
            break

    console.log(f"[bold green][ ! ] [bold white]results saved to [bold yellow]'{dig_obj.output_file_path}'[/]")

def run():
    """ Runs Unlisted """
    # pyt reads channel pages with urlopen and no timeout; this keeps a dead
    # connection from hanging the whole run.
    socket.setdefaulttimeout(15)

    constants.banner()
    cli()

if __name__ == "__main__":
    run()
