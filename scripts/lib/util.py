#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# dependencies = ["pudb", "ipython"]
# ///
import re
import asyncio
import logging as log
import datetime as dt
import subprocess as sp


EN_DE_WEEKDAYS = {
    "Monday"    : "Mo.",
    "Tuesday"   : "Di.",
    "Wednesday" : "Mi.",
    "Thursday"  : "Do.",
    "Friday"    : "Fr.",
    "Saturday"  : "Sa.",
    "Sunday"    : "So.",
}


def get_weekday_de(date_str: str) -> str:
    """Returns the German weekday for a yyyy-mm-dd date string."""
    try:
        en_weekday = dt.date.fromisoformat(date_str).strftime("%A")
        return EN_DE_WEEKDAYS.get(en_weekday, "")
    except ValueError:
        return ""


assert get_weekday_de('2020-01-01') == "Mi."


def run_git(*args) -> sp.CompletedProcess:
    str_args = list(map(str, args))
    log.info("Running: git " + " ".join(str_args))
    proc = sp.run(["git"] + str_args, check=True, capture_output=True, text=True)
    log.info(f"Completed with retcode: {proc.returncode}")
    return proc


def git_push(sheet_id: str, message: str, repo_paths: list[str]) -> list[str]:
    try:
        run_git("add", *repo_paths)

        proc = run_git("status")
        if "Changes to be committed:" not in proc.stdout:
            log.info(f"No changes to be committed for {repo_paths}")
            return []

        git_status_re =  re.compile(r"(Changes to be committed:|Changes not staged for commit:|Untracked files:)", flags=re.MULTILINE)
        parts = git_status_re.split(proc.stdout)
        sections = dict(zip(parts[1::2], parts[2::2]))
        modified_files = [
            match.group(1)
            for match in re.finditer(r"modified:\s+(\S+)", sections["Changes to be committed:"])
        ]

        run_git("commit", "-m", message)
        run_git("push")

        log.info("Git sync and push completed successfully.")
        return modified_files
    except Exception as ex:
        log.error(f"Error during git sync and push: {ex}")
        # Note: We don't notify the user here as it's a background operation


