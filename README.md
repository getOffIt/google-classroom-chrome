# Google Classroom Chrome launcher

Run on macOS with Google Chrome and Python 3 installed. Copy `credentials.example.json` to `credentials.json` and enter your school email
and password in `credentials.json`, then run:

```sh
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
python3 classroom.py
```

The script opens Google Classroom in a separate Chrome profile and
attempts automatic sign-in by default. Later runs reuse Chrome's saved session.
Complete any school or Google verification in the browser when required.
The start URL is `https://classroom.google.com/h/st`. Chrome browser sign-in is
disabled for this dedicated profile; you sign into the Classroom website only.

The profile contains signed-in browser data, so keep it private. Its default location is
`~/Library/Application Support/Classroom Chrome`, outside this repository.
This profile is separate from your everyday Chrome profile.

To use another dedicated profile:

```sh
python3 classroom.py --profile-dir "$HOME/Library/Application Support/Other Classroom Chrome"
```

Use a dedicated directory for this option, not your everyday Chrome data folder.
To sign out, use Google's account menu in the Classroom browser window.

## Sign-in options

`--auto-login` is enabled by default and can still be passed explicitly.
To open Chrome without attempting automatic sign-in:

```sh
python3 classroom.py --no-auto-login
```

If the dedicated Classroom Chrome instance is already open, the script closes it
gracefully before relaunching. This closes all tabs in that dedicated profile;
other Chrome profiles are left alone.
The automatic mode keeps Chrome open until you press Enter in the terminal.
It reuses the saved session and attempts the standard Google email/password flow
once when presented. Account chooser pages, school SSO, verification challenges,
and Google's restrictions on automated browsers may require manual intervention.
It cannot guarantee permanent unattended access.

`credentials.json` stores the password in plain text and is excluded from Git.
Anyone who can read it can read the password. Enter credentials locally in VS Code.
Neither mode reads assignments.

## Local files

Credentials, browser profiles, virtual environments, screenshots, and diagnostic
artifacts must stay local. Only the blank credentials example is included.
This script currently opens Classroom; it does not extract homework or submit work.

## OpenClaw integration

`--non-interactive` closes the browser after checking and returns a nonzero exit
code when authentication or account verification fails. `--session-only` avoids
submitting credentials. `--expected-email` requires a matching visible account
identity. `--native-keychain` uses the native macOS Keychain rather than
Playwright's mock Keychain and basic password store.

Stop the dedicated browser profile through OpenClaw before running this script
against it. Configure the account and profile path locally, for example:

```sh
.venv/bin/python classroom.py --non-interactive --native-keychain \
  --expected-email "$CLASSROOM_EMAIL" \
  --profile-dir "$CLASSROOM_PROFILE_DIR"
```

Reopen the same dedicated profile in OpenClaw afterward and verify the account
and class. Do not run concurrently with other browser tasks. Stop on verification
or authentication challenges rather than repeatedly retrying sign-in. Add
`--session-only` to check saved-session reuse without submitting credentials.
The script does not change homework state.

Keep screenshots from `--diagnose` private; they may contain account and class
information. They are excluded from Git along with credentials and local artifacts.
