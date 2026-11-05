import re

__all__ = [
    "is_url",
    "channel_url"
]

# Stubs
def is_url(text: str) -> bool: ...
def channel_url(channel_name: str) -> str: ...

# Implementation
def is_url(text: str) -> bool:
    """ Checks if a text is a url or not """
    regex = r'https?://[-A-Za-z0-9+&@#/%?=~_|!:,.;]*[-A-Za-z0-9+&@#/%=~_|]'

    return re.match(regex, text) is not None

def channel_url(channel_name: str) -> str:
    """ Returns the channel url off the channel name """
    return f"https://youtube.com/@{channel_name}"
