#!/usr/bin/env python3
"""
Heroes of History - Player Data Fetcher
Fetches individual player data from the game API
"""

import requests
import re
import uuid
import base64
import json
import os
from datetime import datetime
from getpass import getpass
import argparse

# Constants
PROTOBUF_CONTENT_TYPE = 'application/x-protobuf'
JSON_CONTENT_TYPE = 'application/json'
GAME_LOGIN_URL = "https://{subdomain}.heroesgame.com/api/login"
ACCOUNT_PLAY_URL = "https://{subdomain}.heroesofhistorygame.com/core/api/account/play"
WAKEUP_API_URL = "https://{world_id}.heroesofhistorygame.com/game/wakeup"
FOG_DATA_URL = "https://forgeofgames-f.azurewebsites.net/api/hoh/inGameData/parse"

# Available collection categories (based on typical game data)
COLLECTION_CATEGORIES = [
    "player",
    "account", 
    "inventory",
    "buildings",
    "heroes",
    "alliance",
    "quests",
    "achievements",
    "resources",
    "troops",
    "research",
    "leaderboards"
]

class HoHDataFetcher:
    def __init__(self, world_id='un1'):
        self.world_id = world_id
        self.session_data = None
        
    def default_headers(self):
        return {"Content-Type": JSON_CONTENT_TYPE}
    
    def bin_data_headers(self):
        if not self.session_data:
            raise Exception("Not logged in")
            
        return {
            "X-AUTH-TOKEN": self.session_data["sessionId"],
            "X-Request-Id": str(uuid.uuid4()),
            "X-Platform": "browser",
            "X-ClientVersion": self.session_data["clientVersion"],
            "Accept-Encoding": "gzip",
            "Content-Type": PROTOBUF_CONTENT_TYPE,
            "Accept": PROTOBUF_CONTENT_TYPE,
        }
    
    def login(self, username, password):
        """Login to the game and establish a session"""
        print("Logging in...")
        session = requests.Session()
        
        payload = {
            "username": username,
            "password": password,
            "useRememberMe": False
        }
        
        subdomain = 'www' if self.world_id.startswith('un') else 'beta'
        response = session.post(
            GAME_LOGIN_URL.format(subdomain=subdomain), 
            headers=self.default_headers(), 
            json=payload
        )
        response.raise_for_status()
        login_data = response.json()
        
        # Get client version from redirect page
        redirect_res = session.get(login_data["redirectUrl"])
        redirect_res.raise_for_status()
        
        client_version_match = re.search(r'const\s+clientVersion\s*=\s*"([^"]+)"', redirect_res.text)
        if not client_version_match:
            raise Exception("Client version not found.")
        
        client_version = client_version_match.group(1)
        print(f"Client version: {client_version}")
        
        # Play on the selected world
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
                "userAgent": "hoh-player-data-fetcher"
            },
            "network": "BROWSER_SESSION",
            "token": "",
            "worldId": None
        }
        
        subdomain = 'un0' if self.world_id.startswith('un') else 'zz0'
        res = session.post(
            ACCOUNT_PLAY_URL.format(subdomain=subdomain), 
            headers=self.default_headers(), 
            json=play_payload
        )
        res.raise_for_status()
        
        self.session_data = res.json()
        self.session_data["clientVersion"] = client_version
        print("Login successful!")
        return True
    
    def get_game_data(self, categories=None):
        """Fetch game data for specified categories"""
        if not self.session_data:
            raise Exception("Not logged in. Please login first.")
        
        # Get binary data from wakeup endpoint
        print("Fetching game data from server...")
        res = requests.post(
            WAKEUP_API_URL.format(world_id=self.world_id), 
            headers=self.bin_data_headers()
        )
        res.raise_for_status()
        bin_data = res.content
        
        # Convert to base64
        base64_data = base64.b64encode(bin_data).decode('utf-8')
        
        # Prepare categories
        if categories is None:
            categories = ["player", "account", "inventory", "buildings", "heroes"]
        
        # Send to FOG API for parsing
        print(f"Parsing data for categories: {', '.join(categories)}")
        payload = {
            "base64ResponseData": base64_data,
            "responseUrl": WAKEUP_API_URL.format(world_id=self.world_id),
            "collectionCategoryIds": categories
        }
        
        res = requests.post(FOG_DATA_URL, headers=self.default_headers(), json=payload)
        res.raise_for_status()
        
        return res.json()
    
    def save_data(self, data, filename=None):
        """Save data to JSON file"""
        if filename is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"player_data_{timestamp}.json"
        
        with open(filename, 'w') as f:
            json.dump(data, f, indent=2)
        
        print(f"Data saved to {filename}")
        return filename

def main():
    parser = argparse.ArgumentParser(description='Fetch Heroes of History player data')
    parser.add_argument('--world', default='un1', choices=['un1', 'zz1'], 
                       help='Game world (un1=main, zz1=beta)')
    parser.add_argument('--categories', nargs='+', 
                       choices=COLLECTION_CATEGORIES,
                       help='Data categories to fetch')
    parser.add_argument('--output', '-o', help='Output filename')
    parser.add_argument('--all-categories', action='store_true',
                       help='Fetch all available categories')
    
    args = parser.parse_args()
    
    print("Heroes of History - Player Data Fetcher")
    print("=" * 50)
    print(f"World: {args.world}")
    print()
    
    # Get credentials
    username = input("Username: ")
    password = getpass("Password: ")
    
    # Create fetcher instance
    fetcher = HoHDataFetcher(world_id=args.world)
    
    try:
        # Login
        fetcher.login(username, password)
        
        # Determine categories
        if args.all_categories:
            categories = COLLECTION_CATEGORIES
        elif args.categories:
            categories = args.categories
        else:
            # Default categories
            categories = ["player", "account", "inventory", "buildings", "heroes"]
        
        # Fetch data
        print(f"\nFetching categories: {', '.join(categories)}")
        data = fetcher.get_game_data(categories)
        
        # Save data
        filename = fetcher.save_data(data, args.output)
        
        # Display summary
        print("\nData fetched successfully!")
        if isinstance(data, dict):
            print("\nSummary:")
            for key, value in data.items():
                if isinstance(value, list):
                    print(f"  {key}: {len(value)} items")
                elif isinstance(value, dict):
                    print(f"  {key}: {len(value)} entries")
                else:
                    print(f"  {key}: {type(value).__name__}")
        elif isinstance(data, list):
            print(f"Total items: {len(data)}")
        
        # Pretty print first few items as example
        print("\nSample data:")
        sample = json.dumps(data, indent=2)[:500] + "..."
        print(sample)
        
    except requests.exceptions.HTTPError as e:
        print(f"\nHTTP Error: {e}")
        print(f"Response: {e.response.text if e.response else 'No response'}")
    except Exception as e:
        print(f"\nError: {e}")
        return 1
    
    return 0

if __name__ == "__main__":
    exit(main())