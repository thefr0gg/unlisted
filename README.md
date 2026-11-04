# unlisted

a tool for digging up unlisted YouTube videos on a channel. it generates random video IDs, checks them against YouTube's oEmbed endpoint, and logs anything that comes back alive.

## how it works

YouTube video IDs are 11 characters from `[a-zA-Z0-9_-]`. unlisted brute-forces that space by generating random IDs, skipping any that belong to the channel's public videos, and checking the rest. if a hit comes back it records the title, URL, and author.

## requirements

- python 3.10+

## install

```bash
git clone https://github.com/thefr0gg/unlisted
cd unlisted
python -m venv .venv
source .venv/bin/activate
pip install .
```

or, if you use [pipx](https://pipx.pypa.io):

```bash
pipx install git+https://github.com/thefr0gg/unlisted
```

## usage

### dig a specific channel

```bash
unlisted dig --channel-identifier LinusTechTips --threads 7
```

pass the channel handle **without** the `@` sign.

### open search (all channels)

```bash
unlisted dig --open --threads 5
```

no channel filter — logs every valid unlisted video it finds regardless of who uploaded it.

### resume a previous run

```bash
unlisted dig --channel-identifier LinusTechTips --ignore-uids-from-result ./unlisted-dig-results-LinusTechTips.json
```

pass the result file from a previous run and it'll skip IDs that were already tested.

### all options

| flag | description | default |
|---|---|---|
| `--channel-identifier` | channel handle to target | — |
| `--open` | search across all channels | false |
| `--threads` | number of worker threads | 3 |
| `--delay` | ms between requests per thread (helps avoid IP blocks) | 500 |
| `--output` | path to save the result file | `./` |
| `--ignore-uids-from-result` | result file to resume from | — |

results are saved to a JSON file in the output directory and auto-saved every 30 seconds while running. press `Ctrl+C` to stop cleanly.

## license

[GPL-3.0](./LICENSE)
