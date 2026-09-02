import json
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow


SCOPES = [
    "https://www.googleapis.com/auth/drive"
]

CLIENT_FILE = Path(
    "google_client_secret.json"
)


if not CLIENT_FILE.exists():
    raise SystemExit(
        "\n"
        "ERROR: google_client_secret.json was not found.\n\n"
        "Put your Google OAuth Client JSON file beside this script "
        "and rename it to:\n\n"
        "google_client_secret.json\n"
    )


try:
    client_config = json.loads(
        CLIENT_FILE.read_text(
            encoding="utf-8"
        )
    )

except json.JSONDecodeError:
    raise SystemExit(
        "\n"
        "ERROR: google_client_secret.json is not valid JSON.\n"
    )


try:

    flow = InstalledAppFlow.from_client_config(
        client_config,
        SCOPES
    )

    credentials = flow.run_local_server(
        port=0,
        access_type="offline",
        prompt="consent"
    )

except Exception as e:

    raise SystemExit(
        f"\nERROR while creating OAuth token:\n{e}\n"
    )


token_json = credentials.to_json()


print(
    "\n"
    "==================================================\n"
    "COPY THIS JSON INTO RENDER\n"
    "==================================================\n"
)

print(token_json)

print(
    "\n"
    "==================================================\n"
    "END TOKEN\n"
    "==================================================\n"
)

print(
    "\n"
    "Render Environment Variable:\n"
    "GDRIVE_OAUTH_TOKEN_JSON\n"
)
