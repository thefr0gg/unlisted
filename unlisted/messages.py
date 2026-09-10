# ------------- error messages ---------------
# NOTE: Please do not change any of the following
# error messages unless their was a typo or some
# of them where hard to understand by the users

OUTPUT_FILE_PATH_NOT_FOUND = "[bold red][ - ] [bold white]The given output file path doesn't not exists[bold white]. Please change it and try again"

RESULT_FILE_PATH_NOT_FOUND = "[bold red][ - ] [bold white]The given result file path doesn't not exists or it's not a file[bold white]. Please change it and try again"
RESULT_FILE_IS_CORRUPTED = "[bold red][ - ] [bold white]The given result file is corrupted[bold white]"

CHANNEL_IDENTIFIER_SHOULD_NOT_BE_A_URL = "[bold red][ - ] [bold white]Channel name should not be a URL"
CHANNEL_IDENTIFIER_REQUIRED = "[bold red][ - ] [bold white]A channel name is missing, which is required for this operation. Alternatively, you can enable the --open flag to continue the search across all channels"

# ------------- info messages ---------------
# NOTE: Please do not change any of the following
# info messages unless their was a typo or some
# of them where hard to understand by the users

CHECKING_CHANNEL_URL = lambda channel_url: f"[bold white]Checking channel URL [bold green]'{channel_url}'[bold white]..."
CHANNEL_URL_IS_NOT_VALID = lambda channel_url: f"[bold red][ - ] [bold white]Invalid channel URL [bold yellow]{channel_url}[bold white]. Please verify the channel URL and try again."

FOUND_UNLISTED_VIDEO_FOR_CURRENT_CHANNEL = lambda video_url, channel_name, thread_index: f"[bold green][ + ] [bold white]THREAD [bold red]#{thread_index}[bold white]: [bold white]Found an unlisted video URL [bold green]'{video_url}'[bold white] for the current channel [bold green]'{channel_name}'[bold white]"
FOUND_UNLISTED_VIDEO_FOR_OTHER_CHANNEL = lambda video_url, channel_name, thread_index: f"[bold green][ + ] [bold white]THREAD [bold red]#{thread_index}[bold white]: [bold white]Found an unlisted video URL [bold green]'{video_url}'[bold white] for channel [bold green]'{channel_name}'[bold white]"
