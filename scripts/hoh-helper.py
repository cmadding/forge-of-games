import requests
import re
import uuid
import base64

# === MANUAL CREDENTIALS ===
USERNAME = "chadmadding@gmail.com"
PASSWORD = ""

# === CONSTANTS ===
PROTOBUF_CONTENT_TYPE = 'application/x-protobuf'
JSON_CONTENT_TYPE = 'application/json'
login_url = "https://www.heroesgame.com/api/login"
account_play_url = "https://un0.heroesofhistorygame.com/core/api/account/play"
startup_api_url = "https://un1.heroesofhistorygame.com/game/startup"
fog_data_url = "https://forgeofgames.com/api/hoh/inGameData"

# === HEADERS ===
def default_headers():
    return {"Content-Type": JSON_CONTENT_TYPE}

def startup_headers(session_data):
    return {
        "X-AUTH-TOKEN": session_data["sessionId"],
        "X-Request-Id": str(uuid.uuid4()),
        "X-Platform": "browser",
        "X-ClientVersion": session_data["clientVersion"],
        "Accept-Encoding": "gzip",
        "Accept": PROTOBUF_CONTENT_TYPE,
        "Content-Type": PROTOBUF_CONTENT_TYPE
    }

# === NETWORK FUNCTIONS ===
def login():
    session = requests.Session()

    payload = {
        "username": USERNAME,
        "password": PASSWORD,
        "useRememberMe": False
    }

    response = session.post(login_url, headers=default_headers(), json=payload)
    response.raise_for_status()
    login_data = response.json()

    redirect_res = session.get(login_data["redirectUrl"])
    redirect_res.raise_for_status()

    client_version_match = re.search(r'const\s+clientVersion\s*=\s*"([^"]+)"', redirect_res.text)
    if not client_version_match:
        raise Exception("Client version not found.")

    client_version = client_version_match.group(1)

    play_payload = {
        "createDeviceToken": False,
        "meta": {
            "clientVersion": client_version,
            "device": "browser",
            "deviceHardware": "browser",
            "deviceManufacturer": "none",
            "deviceName": "browser",
            "locale": "en_DK",
            "networkType": "wlan",
            "operatingSystemName": "browser",
            "operatingSystemVersion": "1",
            "userAgent": "hoh-helper-mobile"
        },
        "network": "BROWSER_SESSION",
        "token": "",
        "worldId": None
    }

    res = session.post(account_play_url, headers=default_headers(), json=play_payload)
    res.raise_for_status()

    session_data = res.json()
    session_data["clientVersion"] = client_version
    return session_data


def get_startup(session_data):
    res = requests.post(startup_api_url, headers=startup_headers(session_data))
    res.raise_for_status()
    return base64.b64encode(res.content).decode('utf-8')

def send_startup(startup_data):
    payload = {
        "inGameStartupData": startup_data
    }
    res = requests.post(fog_data_url, headers=default_headers(), json=payload)
    return res.json()

# === MAIN FUNCTION ===
def main():
    print("Logging in...")
    session_data = login()
    print("Session data received")

    print("Fetching startup data...")
    startup_data = get_startup(session_data)
    print("Startup data received")

    print("Sending startup data...")
    fog_response = send_startup(startup_data)
    if fog_response.get("webResourceUrl"):
        print("Fog data received!")
        print("Open in browser:", fog_response["webResourceUrl"])
        try:
            import webbrowser
            webbrowser.open(fog_response["webResourceUrl"])
        except:
            pass
    else:
        print("No URL returned from server.")

if __name__ == "__main__":
    main()