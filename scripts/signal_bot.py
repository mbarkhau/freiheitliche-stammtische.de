#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# dependencies = [
#   "pudb", "ipython",
#   "requests",
#   "signalbot",
# ]
# ///
"""Bot for Signal Messanger. Regularly runs polls to keep people engaged.

Usage:
    uv run --script signal_bot.py [options]

Options:
    -v, --verbose         Enable verbose logging
    -q, --quiet           Enable quiet logging
    -h, --help            Show this help message and exit
"""
import sys
import json
import logging
import argparse
import pathlib as pl
import typing as typ
from utils import cli

import signalbot

log = logging.getLogger(name="signal_bot.py")

def main(argv: list[str] = sys.argv[1:]) -> int:
    subcmd, args = cli.parse_args(argv, __doc__)
    cli.init_logging(args)

    log.info("Starting signal bot")

    bot = signalbot.SignalBot()
    


if __name__ == "__main__":
    sys.exit(main())
