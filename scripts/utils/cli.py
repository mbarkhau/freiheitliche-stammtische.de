import re
import sys
import logging
import argparse


_option_pattern = r"""
(?P<option_name>--\w[\w\-]+)
\s+
(?P<option_value>\<[\w\-]+\>)
\s+
(?P<option_help>\w.*)
"""
_option_re = re.compile(_option_pattern, flags=re.VERBOSE)

_flag_pattern = r"""
(
   (?P<flag_short>-\w)
   ,\s*
)?
(?P<flag_name>--\w[\w\-]+)
\s+
(?P<flag_help>\w.*)
"""
_flag_re = re.compile(_flag_pattern, flags=re.VERBOSE)


def _parse_docstring(doc: str) -> tuple[list[tuple[str, str, str]], list[tuple[str, str, str]]]:
    options = []
    for match in _option_re.finditer(doc):
        option_name = match.group("option_name")
        option_value = match.group("option_value")
        option_help = match.group("option_help")
        options.append((option_name, option_value, option_help))
    
    flags = []
    for match in _flag_re.finditer(doc):
        flag_name = match.group("flag_name")
        flag_short = match.group("flag_short")
        flag_help = match.group("flag_help")
        flags.append((flag_short, flag_name, flag_help))
    return (options, flags)


_test_docstring = """
Test description.

Usage:
    script_name.py [--opt-name <opt_val>]

Options:
    --opt-name <opt_val>  Description of option
    -v, --verbose         Enable verbose logging
    -q, --quiet           Enable quiet logging
    -h, --help            Show this help message and exit
"""


if __name__ == "__main__":
    options, flags = _parse_docstring(_test_docstring)
    assert options == [
        ("--opt-name", "<opt_val>", "Description of option")
    ]
    assert flags == [
        ("-v", "--verbose", "Enable verbose logging"),
        ("-q", "--quiet", "Enable quiet logging"),
        ("-h", "--help", "Show this help message and exit"),
    ]


class ArgumentParser(argparse.ArgumentParser):

    def __init__(self, doc: str, *args, **kwargs):
        super().__init__(
            description=doc,
            formatter_class=argparse.RawDescriptionHelpFormatter,
            *args,
            **kwargs,
        )

    def format_help(self):
        return self.description + "\n"


def _init_arg_parser(doc: str, defaults: dict[str, str]) -> argparse.ArgumentParser:
    parser = ArgumentParser(doc)
    
    options, flags = _parse_docstring(doc)
    for option_name, option_value, option_help in options:
        parser.add_argument(option_name, nargs="?", default=defaults[option_name], help=option_help)

    for flag_short, flag_name, flag_help in flags:
        if flag_name == "--help":
            continue
        parser.add_argument(flag_short, flag_name, action="store_true", help=flag_help)

    # TODO (mb - 2025-11-23): Support config files (e.g. .env, .ini, .toml).
    # TODO (mb - 2025-11-23): Set defaults based on environment variables.
    #       Priority: CLI Argument > Environment Variable > Config File > Docstring
    return parser


def parse_args(argv: list[str], doc: str, defaults: dict[str, str] = {}) -> argparse.Namespace:
    parser = _init_arg_parser(doc, defaults)
    args = parser.parse_args(argv)
    return args


def init_logging(args: argparse.Namespace) -> None:
    if args.verbose:
        level = logging.DEBUG
    elif args.quiet:
        level = logging.ERROR
    else:
        level = logging.INFO

    logging.basicConfig(
        level=level,
        format="%(asctime)s.%(msecs)03d - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )

