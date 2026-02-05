#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# dependencies = ["pudb", "ipython"]
# ///
import re
import sys
import json
import logging
import argparse


_option_pattern = r"""
(
   (?P<option_short>-\w)
   (?:,\s*|\s+)
)?
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
   (?:,\s*|\s+)
)?
(?P<flag_name>--\w[\w\-]+)
\s+
(?P<flag_help>\w.*)
"""
_flag_re = re.compile(_flag_pattern, flags=re.VERBOSE)

_command_pattern = r"""
^\s+
(?P<command_name>[\w\-]+)
\s+
(?P<command_help>\w.*)
$
"""
_command_re = re.compile(_command_pattern, flags=re.VERBOSE | re.MULTILINE)


log = logging.getLogger('util.cli')


def _parse_docstring(doc: str) -> tuple[list[tuple[str, str]], list[tuple[str, str, str]], list[tuple[str, str, str]]]:
    sub_commands = []
    # Only look for commands in the "Commands:" section
    commands_section_match = re.search(r"(?s)(^Commands:\n)(.*?)(?:\n\n|\Z)", doc, re.MULTILINE)
    if commands_section_match:
        commands_block = commands_section_match.group(2)
        for match in _command_re.finditer(commands_block):
            command_name = match.group("command_name")
            command_help = match.group("command_help")
            sub_commands.append((command_name, command_help))

    options = []
    for match in _option_re.finditer(doc):
        option_short = match.group("option_short")
        option_name = match.group("option_name")
        option_value = match.group("option_value")
        option_help = match.group("option_help")
        options.append((option_short, option_name, option_value, option_help))
    
    flags = []
    for match in _flag_re.finditer(doc):
        flag_name = match.group("flag_name")
        flag_short = match.group("flag_short")
        flag_help = match.group("flag_help")
        flags.append((flag_short, flag_name, flag_help))
    return (sub_commands, options, flags)


_test_docstring = """
Test description.

Usage:
    script_name.py [--opt-name <opt_val>]
    script_name.py my-sub-command [--opt-name <opt_val>]

Commands:
    my-sub-command        Description of sub-command

Options:
    -o --opt-name <opt_val>  Description of option
    -v, --verbose         Enable verbose logging
    -q, --quiet           Enable quiet logging
    -h, --help            Show this help message and exit
"""


if __name__ == "__main__":
    # self test
    sub_commands, options, flags = _parse_docstring(_test_docstring)
    assert sub_commands == [
        ("my-sub-command", "Description of sub-command")
    ]
    assert options == [
        ("-o", "--opt-name", "<opt_val>", "Description of option")
    ]
    assert flags == [
        ("-v", "--verbose", "Enable verbose logging"),
        ("-q", "--quiet", "Enable quiet logging"),
        ("-h", "--help", "Show this help message and exit"),
    ]


class ArgumentParser(argparse.ArgumentParser):

    def __init__(self, doc: str = None, *args, **kwargs):
        if doc is None:
            doc = kwargs.get("description")
        if "description" in kwargs:
            del kwargs["description"]

        super().__init__(
            description=doc,
            formatter_class=argparse.RawDescriptionHelpFormatter,
            *args,
            **kwargs,
        )

    def format_help(self):
        return self.description + "\n"


def _add_arguments(parser: argparse.ArgumentParser, options: list, flags: list, defaults: dict[str, str]) -> None:
    for option_short, option_name, option_value, option_help in options:
        args = []
        if option_short:
            args.append(option_short)
        args.append(option_name)
        parser.add_argument(*args, nargs="?", default=defaults.get(option_name), help=option_help)

    for flag_short, flag_name, flag_help in flags:
        if flag_name == "--help":
            continue
        
        flag_args = []
        if flag_short:
            flag_args.append(flag_short)
        flag_args.append(flag_name)
        
        parser.add_argument(*flag_args, action="store_true", help=flag_help)


def _init_arg_parser(doc: str, defaults: dict[str, str]) -> argparse.ArgumentParser:
    parser = ArgumentParser(doc)
    
    sub_commands, options, flags = _parse_docstring(doc)

    _add_arguments(parser, options, flags, defaults)

    if sub_commands:
        subparsers = parser.add_subparsers(dest="subcmd")
        for cmd_name, cmd_help in sub_commands:
            subparser = subparsers.add_parser(name=cmd_name, help=cmd_help, description=cmd_help)
            _add_arguments(subparser, options, flags, defaults)

    # TODO (mb - 2025-11-23): Support config files (e.g. .env, .ini, .toml).
    # TODO (mb - 2025-11-23): Set defaults based on environment variables.
    #       Priority: CLI Argument > Environment Variable > Config File > Docstring
    return parser


def parse_args(argv: list[str], doc: str, defaults: dict[str, str] = {}) -> tuple[str, argparse.Namespace]:
    parser = _init_arg_parser(doc, defaults)
    args = parser.parse_args(argv)
    return getattr(args, "subcmd", None), args


if __name__ == "__main__":
    # self test
    subcmd, args = parse_args([], doc=_test_docstring)
    assert subcmd == None 
    assert args.opt_name == None
    subcmd, args = parse_args(["my-sub-command", "--opt-name", "opt_val"], doc=_test_docstring)
    assert subcmd == "my-sub-command"
    assert args.opt_name == "opt_val"


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


def _json_dumps_pretty(obj: dict | list | str | int | float | bool | None, lvl: int = 0) -> str:
    if obj is None:
        return "null"
    elif isinstance(obj, str):
        return json.dumps(obj)
    elif isinstance(obj, bool):
        return str(obj).lower()
    elif isinstance(obj, (int, float)):
        return str(obj)
    if isinstance(obj, tuple):
        return _json_dumps_pretty(list(obj), lvl=lvl)
    elif isinstance(obj, list):
        has_nested = any(isinstance(item, (list, dict, tuple)) for item in obj)
        if has_nested:
            indent_str = "  " * (lvl + 1)
            closing_indent = "  " * lvl
            return "[\n" + ",\n".join(indent_str + _json_dumps_pretty(item, lvl=lvl + 1) for item in obj) + "\n" + closing_indent + "]"
        else:
            return "[" + ", ".join(_json_dumps_pretty(item) for item in obj) + "]"
    elif isinstance(obj, dict):
        has_nested = any(isinstance(item, (list, dict, tuple)) for item in obj.values())
        if has_nested or len(obj) > 4:
            indent_str = "  " * (lvl + 1)
            closing_indent = "  " * lvl
            return "{\n" + ",\n".join(indent_str + json.dumps(key) + ': ' + _json_dumps_pretty(val, lvl=lvl + 1) for key, val in obj.items()) + "\n" + closing_indent + "}"
        else:
            return "{" + ", ".join(json.dumps(key) + ': ' + _json_dumps_pretty(val) for key, val in obj.items()) + "}"
    else:
        raise ValueError("Unsupported type: " + type(obj).__name__)


def json_dumps_pretty(obj: dict | list | str | int | float | bool | None) -> str:
    fallback = json.dumps(obj, indent=2)
    expected = json.loads(fallback)
    try:
        result = _json_dumps_pretty(obj)
        if json.loads(result) == expected:
            return result
        else:
            log.warning("json_dumps encode error. fallback to builtin")
    except Exception as ex:
        log.warning(f"json_dumps encode error. fallback to builtin {ex}")

    return fallback



if __name__ == "__main__":
    assert json_dumps_pretty("a") == '"a"'
    assert json_dumps_pretty(True) == 'true'
    assert json_dumps_pretty(False) == 'false'
    assert json_dumps_pretty(None) == 'null'
    assert json_dumps_pretty((1, 2, 3)) == '[1, 2, 3]'
    assert json_dumps_pretty([1, 2, 3]) == '[1, 2, 3]'
    assert json_dumps_pretty({"a": 1, "b": 2, "c": 3}) == '{"a": 1, "b": 2, "c": 3}'
    expected = '{\n  "a": [1, 2, 3],\n  "b": [4, 5, 6],\n  "c": {"d": 7, "e": 8}\n}'
    assert json_dumps_pretty({"a": (1, 2, 3), "b": [4, 5, 6], "c": {"d": 7, "e": 8}}) == expected
