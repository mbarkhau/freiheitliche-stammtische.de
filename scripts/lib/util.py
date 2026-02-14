import asyncio
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


async def git_sync_and_push(sheet_id: str, message: str, repo_paths: list[str]) -> None:
    try:
        log.info(f"Starting git sync and push: {message}...")
        # 1. Sync from GSheet to JSON files
        await asyncio.to_thread(gu.sync_cmd, sheet_id)

        # 2. Git operations
        def run_git(args):
            log.info(f"Running git {' '.join(args)}")
            sp.run(["git"] + list(args), check=True, capture_output=True, text=True)

        await asyncio.to_thread(run_git, ["add"] + repo_paths)
        await asyncio.to_thread(run_git, ["commit", "-m", message])
        await asyncio.to_thread(run_git, ["push"])

        log.info("Git sync and push completed successfully.")
        gu.GSheet(sheet_id).log(f"Git push successful: {message}")
    except Exception as ex:
        log.error(f"Error during git sync and push: {ex}")
        # Note: We don't notify the user here as it's a background operation


