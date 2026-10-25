#!/usr/bin/env python3
"""Open Google Classroom in a dedicated, persistent Chrome profile."""

import argparse
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time
from urllib.parse import urlparse

START_URL = "https://classroom.google.com/h/st"


def account_paths(account=None):
    if account and not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", account):
        raise ValueError("Account names must contain lowercase letters, digits, underscores or hyphens.")
    root = Path(__file__).resolve().parent
    if account:
        return (root / ".local" / "accounts" / f"{account}.json",
                Path.home() / "Library/Application Support/Classroom Chrome Accounts" / account)
    return root / "credentials.json", Path.home() / "Library/Application Support/Classroom Chrome"


def load_credentials(path, session_only=False):
    if session_only and not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
        if not isinstance(data, dict):
            raise ValueError
        for key in (["email"] if session_only else ["email", "password"]):
            if not isinstance(data.get(key), str) or not data[key].strip():
                raise ValueError
        return data
    except (OSError, ValueError):
        raise ValueError("Set email and password in the selected local credentials file as one JSON object.") from None


def close_profile_browser(profile: Path) -> None:
    """Gracefully stop only the Chrome process owning this profile's lock."""
    lock = profile / "SingletonLock"
    if not lock.is_symlink():
        if lock.exists():
            raise ValueError("Unrecognized Chrome profile lock; close its browser manually.")
        return
    try:
        pid = int(os.readlink(lock).rsplit("-", 1)[1])
    except (ValueError, IndexError):
        raise ValueError("Unrecognized Chrome profile lock; close its browser manually.")
    if pid <= 1:
        raise ValueError("Invalid Chrome process ID in profile lock.")
    process = subprocess.run(
        ["ps", "-p", str(pid), "-o", "comm=", "-o", "args="],
        capture_output=True, text=True, check=False,
    )
    if process.returncode != 0:
        # A crashed browser may leave a stale lock; Chrome handles it on startup.
        return
    command = process.stdout.strip()
    profile_argument = re.escape(f"--user-data-dir={profile}") + r"(?=\s--|$)"
    if "/Google Chrome.app/Contents/MacOS/Google Chrome" not in command or not re.search(profile_argument, command):
        raise ValueError("Profile lock belongs to an unexpected process; refusing to close it.")
    print("Closing the existing Classroom Chrome window before relaunching...")
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    deadline = time.monotonic() + 15
    while lock.is_symlink() or lock.exists():
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            # The process is gone. Chrome can recover its stale lock on startup.
            return
        if time.monotonic() >= deadline:
            raise ValueError("Classroom Chrome did not finish closing within 15 seconds. Close it manually and retry.")
        time.sleep(0.1)


def prepare_profile(profile: Path) -> None:
    """Allow website sessions while keeping Chrome itself signed out."""
    close_profile_browser(profile)
    preferences_path = profile / "Default" / "Preferences"
    preferences_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    preferences = json.loads(preferences_path.read_text()) if preferences_path.exists() else {}
    preferences.setdefault("signin", {}).update(
        {"allowed": False, "allowed_on_next_startup": False}
    )
    preferences_path.write_text(json.dumps(preferences))
    preferences_path.chmod(0o600)


def auto_login(profile: Path, *, credentials=None, non_interactive=False, session_only=False, expected_email=None, native_keychain=False) -> int:
    """Attempt Google's standard email/password flow once, without retries."""
    credentials = credentials or {}
    email, password = credentials.get("email", ""), credentials.get("password", "")
    try:
        from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout, Error as PlaywrightError
    except ImportError:
        print("Install the dependency: python3 -m pip install -r requirements.txt", file=sys.stderr)
        return 1

    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            str(profile), channel="chrome", headless=False, chromium_sandbox=True,
            ignore_default_args=["--use-mock-keychain", "--password-store=basic"] if native_keychain else None,
        )
        try:
            page = context.pages[0] if context.pages else context.new_page()
            page.goto(START_URL, wait_until="domcontentloaded")
            result = 2
            stage = "opening Classroom"
            try:
                # Only submit credentials to Google's own sign-in origin.
                if session_only and urlparse(page.url).hostname == "accounts.google.com":
                    raise ValueError("Saved session requires re-authentication.")
                if urlparse(page.url).hostname == "accounts.google.com":
                    if "accountchooser" in urlparse(page.url).path:
                        stage = "selecting the configured account"
                        account = page.get_by_text(email, exact=True)
                        if account.count():
                            account.first.click()
                        else:
                            page.get_by_text("Use another account", exact=True).click()
                    stage = "waiting for Google's email field"
                    email_field = page.locator('input#identifierId')
                    page.locator('input#identifierId:visible, input[type="password"]:visible').first.wait_for(state="visible", timeout=15000)
                    if email_field.is_visible():
                        email_field.fill(email)
                        page.locator("#identifierNext").click()
                    stage = "waiting for Google's password field"
                    password_field = page.locator('input[type="password"]:visible')
                    password_field.wait_for(state="visible", timeout=15000)
                    if urlparse(page.url).hostname != "accounts.google.com":
                        raise ValueError("Sign-in left Google's sign-in page.")
                    password_field.fill(password)
                    page.locator("#passwordNext").click()
                stage = "waiting for Classroom after sign-in"
                page.wait_for_url("https://classroom.google.com/**", timeout=30000)
                page.locator("main").wait_for(state="visible", timeout=30000)
                print(f"Loaded page: {page.title()}")
                print(f"Location: {urlparse(page.url).hostname}{urlparse(page.url).path}")
                if "--diagnose" in sys.argv:
                    output = Path(__file__).with_name(".artifacts")
                    output.mkdir(exist_ok=True, mode=0o700)
                    page.screenshot(path=str(output / "classroom.png"))
                if expected_email:
                    quoted_email = json.dumps(expected_email)
                    identity = page.locator(f'[aria-label*={quoted_email}], [title*={quoted_email}]')
                    identity.first.wait_for(state="visible", timeout=10000)
                    print("Expected account identity verified.")
                result = 0
                print("Classroom opened.")
            except (PlaywrightTimeout, ValueError):
                print(f"Stopped while {stage}.")
                body = page.locator("body").inner_text()
                print(f"Page: {urlparse(page.url).hostname}{urlparse(page.url).path}")
                if "browser or app may not be secure" in body.lower():
                    print("Google rejected this automated browser as insecure.")
                elif "verify" in body.lower() or "verification" in body.lower():
                    print("Google is showing a verification step.")
                print("Automatic sign-in did not finish. Check Chrome for account selection, verification, or a sign-in error.")
            if not non_interactive:
                input("Press Enter here when finished to close this Chrome window: ")
            return result
        finally:
            try:
                context.close()
            except PlaywrightError as error:
                if "has been closed" not in str(error):
                    raise
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--account", help="Local account name; uses .local/accounts/NAME.json and an isolated Chrome profile")
    parser.add_argument("--native-keychain", action="store_true", help="Use native macOS Keychain, matching OpenClaw Chrome")
    parser.add_argument("--non-interactive", action="store_true", help="Close after checking; return nonzero if authentication or identity fails")
    parser.add_argument("--session-only", action="store_true", help="Check saved session without submitting credentials")
    parser.add_argument("--expected-email", help="Require matching visible Google account identity")
    parser.add_argument("--diagnose", action="store_true", help="Save a local screenshot after Classroom loads")
    login_options = parser.add_mutually_exclusive_group()
    login_options.add_argument("--auto-login", dest="auto_login", action="store_true", help="Attempt sign-in using local credentials.json (default)")
    login_options.add_argument("--no-auto-login", dest="auto_login", action="store_false", help="Open Chrome without attempting automatic sign-in")
    parser.set_defaults(auto_login=True)
    parser.add_argument(
        "--profile-dir",
        type=Path,
        default=None,
        help="Override the account's dedicated Chrome session directory",
    )
    args = parser.parse_args()
    if sys.platform != "darwin":
        parser.error("This launcher currently supports macOS only.")

    chrome_paths = [
        Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
        Path.home() / "Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    ]
    chrome = next((path for path in chrome_paths if path.is_file()), None)
    if chrome is None:
        print("Google Chrome was not found. Install Chrome and run again.", file=sys.stderr)
        return 1

    if args.auto_login:
        try:
            import playwright.sync_api
        except ImportError:
            print(
                f'Install the dependency: "{sys.executable}" -m pip install -r requirements.txt',
                file=sys.stderr,
            )
            return 1

    try:
        credentials_path, default_profile = account_paths(args.account)
        credentials = load_credentials(credentials_path, args.session_only) if args.auto_login else {}
        if args.account and args.expected_email and credentials.get("email") and args.expected_email.casefold() != credentials["email"].casefold():
            raise ValueError("Expected email does not match the selected account's credentials.")
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return 1
    expected_email = args.expected_email or (credentials.get("email") if args.account else None)
    profile = (args.profile_dir or default_profile).expanduser().resolve()
    profile.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        prepare_profile(profile)
    except (OSError, ValueError) as error:
        print(f"Could not prepare Chrome profile: {error}", file=sys.stderr)
        return 1
    if args.auto_login:
        return auto_login(profile, credentials=credentials, non_interactive=args.non_interactive, session_only=args.session_only, expected_email=expected_email, native_keychain=args.native_keychain)
    try:
        # Launch ordinary Chrome so Google sign-in runs in a normal browser.
        subprocess.Popen(
            [str(chrome), f"--user-data-dir={profile}",
             "--new-window", START_URL],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError as error:
        print(f"Could not launch Chrome: {error}", file=sys.stderr)
        return 1
    print("Opened Chrome for Classroom.")
    print("If prompted, sign in with your school Google account in Chrome.")
    print("Chrome will save that session for subsequent runs.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
