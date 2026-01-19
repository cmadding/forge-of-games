#!/usr/bin/env python3
"""
Heroes of History - Local Data Analyzer
Downloads and analyzes your game data locally without uploading anywhere
"""

import os
import re
import uuid
import requests
import json
import base64
from datetime import datetime
from getpass import getpass
import argparse
from typing import Dict, List, Any

# Constants
PROTOBUF_CONTENT_TYPE = 'application/x-protobuf'
JSON_CONTENT_TYPE = 'application/json'

# URLs for main server (change subdomain for beta: www->beta, un0->zz0, un1->zz1)
GAME_LOGIN_URL = "https://{subdomain}.heroesgame.com/api/login"
ACCOUNT_PLAY_URL = "https://{subdomain}.heroesofhistorygame.com/core/api/account/play"
STARTUP_API_URL = "https://{world_id}.heroesofhistorygame.com/game/startup"
WAKEUP_API_URL = "https://{world_id}.heroesofhistorygame.com/game/wakeup"

# Forge of Games parsing service (we'll use this locally only)
FOG_PARSE_URL = "https://forgeofgames-f.azurewebsites.net/api/hoh/inGameData/parse"

class HoHLocalAnalyzer:
    MANUAL_PLAYER_NAME = "Baylore"
    MANUAL_ALLIANCE_NAME = "Mintfield"
    def __init__(self, world_id='un1', data_dir='hoh_local_data'):
        self.world_id = world_id
        self.data_dir = data_dir
        self.session_data = None
        self.is_beta = world_id.startswith('zz')
        self.game_data = {}
        
    def default_headers(self):
        return {"Content-Type": JSON_CONTENT_TYPE}
    
    def api_headers(self, accept_type=PROTOBUF_CONTENT_TYPE):
        if not self.session_data:
            raise Exception("Not logged in")
            
        return {
            "X-AUTH-TOKEN": self.session_data["sessionId"],
            "X-Request-Id": str(uuid.uuid4()),
            "X-Platform": "browser",
            "X-ClientVersion": self.session_data["clientVersion"],
            "Accept-Encoding": "gzip",
            "Content-Type": PROTOBUF_CONTENT_TYPE,
            "Accept": accept_type,
        }
    
    def setup_directories(self):
        """Create data directory structure"""
        os.makedirs(self.data_dir, exist_ok=True)
        os.makedirs(os.path.join(self.data_dir, 'raw'), exist_ok=True)
        os.makedirs(os.path.join(self.data_dir, 'parsed'), exist_ok=True)
        os.makedirs(os.path.join(self.data_dir, 'analysis'), exist_ok=True)
        
    def login(self, username, password):
        """Login to the game"""
        print("🔐 Logging in...")
        session = requests.Session()
        
        payload = {
            "username": username,
            "password": password,
            "useRememberMe": False
        }
        
        subdomain = 'beta' if self.is_beta else 'www'
        response = session.post(
            GAME_LOGIN_URL.format(subdomain=subdomain), 
            headers=self.default_headers(), 
            json=payload
        )
        response.raise_for_status()
        login_data = response.json()
        
        # Get client version
        redirect_res = session.get(login_data["redirectUrl"])
        redirect_res.raise_for_status()
        
        client_version_match = re.search(r'const\s+clientVersion\s*=\s*"([^"]+)"', redirect_res.text)
        if not client_version_match:
            raise Exception("Client version not found.")
        
        client_version = client_version_match.group(1)
        print(f"📌 Client version: {client_version}")
        
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
                "userAgent": "hoh-local-analyzer"
            },
            "network": "BROWSER_SESSION",
            "token": "",
            "worldId": None
        }
        
        subdomain = 'zz0' if self.is_beta else 'un0'
        res = session.post(
            ACCOUNT_PLAY_URL.format(subdomain=subdomain), 
            headers=self.default_headers(), 
            json=play_payload
        )
        res.raise_for_status()
        
        self.session_data = res.json()
        self.session_data["clientVersion"] = client_version
        print("✅ Login successful!")
        return True
    
    def fetch_all_data(self):
        """Fetch all available game data"""
        print("\n📥 Downloading game data...")
    
        # Fetch startup data
        print("  • Fetching startup data...")
        startup_url = STARTUP_API_URL.format(world_id=self.world_id)
        startup_bin = self._fetch_binary(startup_url)
        startup_json = self._fetch_json(startup_url)
    
        # Save raw data
        self._save_data(startup_bin, 'raw/startup.bin', binary=True)
        self._save_data(startup_json, 'raw/startup.json')
    
        # Fetch wakeup data
        print("  • Fetching wakeup data...")
        wakeup_url = WAKEUP_API_URL.format(world_id=self.world_id)
        wakeup_bin = self._fetch_binary(wakeup_url)
        wakeup_json = self._fetch_json(wakeup_url)
    
        # Save raw data
        self._save_data(wakeup_bin, 'raw/wakeup.bin', binary=True)
        self._save_data(wakeup_json, 'raw/wakeup.json')
    
        # Try to parse startup data using the working FOG endpoint
        print("  • Processing startup data...")
        try:
            base64_startup = base64.b64encode(startup_bin).decode('utf-8')
            fog_response = requests.post(
                "https://forgeofgames.com/api/hoh/inGameData",
                headers=self.default_headers(),
                json={"inGameStartupData": base64_startup}
            )
            fog_response.raise_for_status()
            fog_data = fog_response.json()
        
            if fog_data.get("webResourceUrl"):
                print(f"  • FOG URL available: {fog_data['webResourceUrl']}")
                self._save_data(fog_data, 'parsed/fog_response.json')
        except Exception as e:
            print(f"  • Note: FOG service error: {e}")
    
        # Store in memory for analysis - work with JSON data directly
        self.game_data = {
            'startup': json.loads(startup_json),
            'wakeup': json.loads(wakeup_json),
            'startup_parsed': {},  # We'll work with JSON directly
            'wakeup_parsed': {}   # We'll work with JSON directly
        }
    
        print("✅ All data downloaded successfully!")
        
    def _fetch_binary(self, url):
        """Fetch binary data from API"""
        res = requests.post(url, headers=self.api_headers(PROTOBUF_CONTENT_TYPE))
        res.raise_for_status()
        return res.content
    
    def _fetch_json(self, url):
        """Fetch JSON data from API"""
        res = requests.post(url, headers=self.api_headers(JSON_CONTENT_TYPE))
        res.raise_for_status()
        return res.text
    
    def _parse_binary_data(self, bin_data, source_url):
        """Parse binary data using FOG service (local use only)"""
        base64_data = base64.b64encode(bin_data).decode('utf-8')

        # Use the correct API endpoint and format
        if 'startup' in source_url:
            payload = {
                "inGameStartupData": base64_data
            }
            fog_url = "https://forgeofgames.com/api/hoh/inGameData"
        else:
            # For wakeup data, use the parse endpoint with different format
            payload = {
                "base64ResponseData": base64_data,
                "responseUrl": source_url,
                "collectionCategoryIds": [
                    "player", "account", "inventory", "buildings", 
                    "heroes", "alliance", "quests", "achievements",
                    "resources", "troops", "research"
                ]
            }
            fog_url = FOG_PARSE_URL
        res = requests.post(fog_url, headers=self.default_headers(), json=payload)
        res.raise_for_status()
        return res.json()
    
    def _save_data(self, data, filename, binary=False):
        """Save data to file"""
        filepath = os.path.join(self.data_dir, filename)
        mode = 'wb' if binary else 'w'
        encoding = None if binary else 'utf-8'  # Add UTF-8 encoding
        
        # Create directory if it doesn't exist
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        
        with open(filepath, mode, encoding=encoding) as f:
            if binary:
                f.write(data)
            else:
                f.write(data if isinstance(data, str) else json.dumps(data, indent=2, ensure_ascii=False))
                
    def load_existing_data(self):
        """Load previously downloaded data"""
        try:
            # Load raw JSON data with UTF-8 encoding
            with open(os.path.join(self.data_dir, 'raw/startup.json'), 'r', encoding='utf-8') as f:
                startup_json = f.read()
            with open(os.path.join(self.data_dir, 'raw/wakeup.json'), 'r', encoding='utf-8') as f:
                wakeup_json = f.read()
            
            # Load parsed data if available
            startup_parsed = {}
            wakeup_parsed = {}
            
            parsed_startup_path = os.path.join(self.data_dir, 'parsed/startup_parsed.json')
            if os.path.exists(parsed_startup_path):
                with open(parsed_startup_path, 'r', encoding='utf-8') as f:
                    startup_parsed = json.load(f)
            
            parsed_wakeup_path = os.path.join(self.data_dir, 'parsed/wakeup_parsed.json')
            if os.path.exists(parsed_wakeup_path):
                with open(parsed_wakeup_path, 'r', encoding='utf-8') as f:
                    wakeup_parsed = json.load(f)
            
            # Store in memory
            self.game_data = {
                'startup': json.loads(startup_json),
                'wakeup': json.loads(wakeup_json),
                'startup_parsed': startup_parsed,
                'wakeup_parsed': wakeup_parsed
            }
            
            print("✅ Existing data loaded successfully!")
            
        except Exception as e:
            raise Exception(f"Failed to load existing data: {e}")
        
    def analyze_player_info(self):
        """Analyze and extract player information"""
        print("\n🔍 Analyzing player data...")
        
        analysis = {
            'player_info': {},
            'resources': {},
            'heroes': [],
            'cities': [],
            'alliance': {},
            'statistics': {}
        }
        
        # Extract from wakeup data (current state)
        wakeup = self.game_data.get('wakeup', {})
        
        # Player basic info
        if 'player' in wakeup:
            player = wakeup['player']
            analysis['player_info'] = {
                'id': player.get('id'),
                'name': player.get('name') or self.MANUAL_PLAYER_NAME,
                'level': player.get('level'),
                'experience': player.get('experience'),
                'vip_level': player.get('vipLevel'),
                'power': player.get('power'),
            }

        # Alliance
        if 'alliance' in wakeup:
            alliance = wakeup['alliance']
            analysis['alliance'] = {
                'id': alliance.get('id'),
                'name': alliance.get('name') or self.MANUAL_ALLIANCE_NAME,
                'level': alliance.get('level'),
                'members': alliance.get('memberCount'),
                'rank': alliance.get('rank')
            }
        
        # Resources
        if 'resources' in wakeup:
            for resource in wakeup['resources']:
                analysis['resources'][resource.get('type', 'unknown')] = resource.get('amount', 0)
        
        # Heroes
        if 'heroes' in wakeup:
            for hero in wakeup['heroes']:
                hero_info = {
                    'id': hero.get('id'),
                    'name': hero.get('name'),
                    'level': hero.get('level'),
                    'stars': hero.get('stars'),
                    'power': hero.get('power'),
                    'skills': hero.get('skills', [])
                }
                analysis['heroes'].append(hero_info)
        
        # Cities
        if 'cities' in wakeup:
            for city in wakeup['cities']:
                city_info = {
                    'id': city.get('id'),
                    'name': city.get('name'),
                    'level': city.get('level'),
                    'coordinates': city.get('coordinates'),
                    'buildings': len(city.get('buildings', []))
                }
                analysis['cities'].append(city_info)
        
        # Alliance
        if 'alliance' in wakeup:
            alliance = wakeup['alliance']
            analysis['alliance'] = {
                'id': alliance.get('id'),
                'name': alliance.get('name'),
                'level': alliance.get('level'),
                'members': alliance.get('memberCount'),
                'rank': alliance.get('rank')
            }
        
        # Statistics
        analysis['statistics'] = {
            'total_heroes': len(analysis['heroes']),
            'total_cities': len(analysis['cities']),
            'highest_hero_level': max([h['level'] for h in analysis['heroes']], default=0),
            'total_hero_power': sum([h.get('power', 0) for h in analysis['heroes']]),
            'data_timestamp': datetime.now().isoformat()
        }
        
        # Save analysis
        self._save_data(analysis, 'analysis/player_analysis.json')
        
        return analysis
    
    def generate_report(self, analysis):
        """Generate a human-readable report"""
        report = []
        report.append("=" * 60)
        report.append("HEROES OF HISTORY - PLAYER ANALYSIS REPORT")
        report.append("=" * 60)
        report.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        report.append(f"World: {self.world_id}")
        report.append("")
        
        # Player Info
        info = analysis['player_info']
        report.append("PLAYER INFORMATION")
        report.append("-" * 30)
        report.append(f"Name: {info.get('name', 'Unknown')}")
        report.append(f"Level: {info.get('level', 0)}")
        report.append(f"Power: {info.get('power', 0):,}")
        report.append(f"VIP Level: {info.get('vip_level', 0)}")
        report.append("")
        
        # Resources
        report.append("RESOURCES")
        report.append("-" * 30)
        for resource, amount in analysis['resources'].items():
            report.append(f"{resource.title()}: {amount:,}")
        report.append("")
        
        # Heroes Summary
        report.append("HEROES SUMMARY")
        report.append("-" * 30)
        report.append(f"Total Heroes: {analysis['statistics']['total_heroes']}")
        report.append(f"Highest Level: {analysis['statistics']['highest_hero_level']}")
        report.append(f"Total Hero Power: {analysis['statistics']['total_hero_power']:,}")
        report.append("")
        
        # Top Heroes
        report.append("TOP 10 HEROES (by level)")
        report.append("-" * 30)
        top_heroes = sorted(analysis['heroes'], key=lambda x: x['level'], reverse=True)[:10]
        for i, hero in enumerate(top_heroes, 1):
            report.append(f"{i}. {hero['name']} - Level {hero['level']} ({hero['stars']}★)")
        report.append("")
        
        # Cities
        report.append("CITIES")
        report.append("-" * 30)
        for city in analysis['cities']:
            report.append(f"• {city['name']} (Level {city['level']}) - {city['buildings']} buildings")
        report.append("")
        
        # Alliance
        if analysis['alliance']:
            report.append("ALLIANCE")
            report.append("-" * 30)
            report.append(f"Name: {analysis['alliance']['name']}")
            report.append(f"Rank: {analysis['alliance']['rank']}")
            report.append(f"Members: {analysis['alliance']['members']}")
        
        report_text = "\n".join(report)
        
        # Save report
        self._save_data(report_text, 'analysis/player_report.txt')
        
        return report_text
    
    def analyze_heroes_detailed(self):
        """Detailed hero analysis"""
        heroes_analysis = {
            'by_level': {},
            'by_stars': {},
            'by_faction': {},
            'skills_summary': {},
            'top_heroes': []
        }
        
        heroes = []
        
        # Try to get heroes from parsed data first
        if 'wakeup_parsed' in self.game_data and 'heroes' in self.game_data['wakeup_parsed']:
            heroes = self.game_data['wakeup_parsed']['heroes']
        elif 'wakeup' in self.game_data and 'heroes' in self.game_data['wakeup']:
            heroes = self.game_data['wakeup']['heroes']
        
        for hero in heroes:
            level = hero.get('level', 0)
            stars = hero.get('stars', 0)
            faction = hero.get('faction', 'Unknown')
            
            # Group by level
            if level not in heroes_analysis['by_level']:
                heroes_analysis['by_level'][level] = []
            heroes_analysis['by_level'][level].append(hero['name'])
            
            # Group by stars
            if stars not in heroes_analysis['by_stars']:
                heroes_analysis['by_stars'][stars] = []
            heroes_analysis['by_stars'][stars].append(hero['name'])
            
            # Group by faction
            if faction not in heroes_analysis['by_faction']:
                heroes_analysis['by_faction'][faction] = []
            heroes_analysis['by_faction'][faction].append(hero['name'])
        
        # Save detailed hero analysis
        self._save_data(heroes_analysis, 'analysis/heroes_detailed.json')
        
        return heroes_analysis
    
    def analyze_resources_over_time(self):
        """Track resources if we have historical data"""
        timestamp = datetime.now().isoformat()
        
        resources = {}
        if 'wakeup' in self.game_data and 'resources' in self.game_data['wakeup']:
            for resource in self.game_data['wakeup']['resources']:
                resources[resource.get('type', 'unknown')] = {
                    'amount': resource.get('amount', 0),
                    'timestamp': timestamp
                }
        
        # Load historical data if exists
        history_file = os.path.join(self.data_dir, 'analysis/resource_history.json')
        history = []
        
        if os.path.exists(history_file):
            with open(history_file, 'r', encoding='utf-8') as f:  # Added encoding='utf-8'
                history = json.load(f)
        
        # Add current snapshot
        history.append({
            'timestamp': timestamp,
            'resources': resources
        })
        
        # Keep only last 100 snapshots
        history = history[-100:]
        
        # Save updated history
        self._save_data(history, 'analysis/resource_history.json')
        
        return resources
    
    def export_to_csv(self, analysis):
        """Export key data to CSV files for spreadsheet analysis"""
        import csv
        
        csv_dir = os.path.join(self.data_dir, 'csv_exports')
        os.makedirs(csv_dir, exist_ok=True)
        
        # Export heroes to CSV
        heroes_csv = os.path.join(csv_dir, 'heroes.csv')
        with open(heroes_csv, 'w', newline='', encoding='utf-8') as f:
            if analysis['heroes']:
                writer = csv.DictWriter(f, fieldnames=['name', 'level', 'stars', 'power'])
                writer.writeheader()
                for hero in analysis['heroes']:
                    writer.writerow({
                        'name': hero.get('name', ''),
                        'level': hero.get('level', 0),
                        'stars': hero.get('stars', 0),
                        'power': hero.get('power', 0)
                    })
        
        # Export resources to CSV
        resources_csv = os.path.join(csv_dir, 'resources.csv')
        with open(resources_csv, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(['Resource', 'Amount'])
            for resource, amount in analysis['resources'].items():
                writer.writerow([resource, amount])
        
        print(f"📊 CSV files exported to: {csv_dir}")
        
    def create_summary_dashboard(self, analysis):
        """Create a summary dashboard in HTML format"""
        html_template = """
        <!DOCTYPE html>
        <html>
        <head>
            <title>Heroes of History - Player Dashboard</title>
            <style>
                body {{ font-family: Arial, sans-serif; margin: 20px; background-color: #f5f5f5; }}
                .container {{ max-width: 1200px; margin: 0 auto; }}
                .card {{ background: white; padding: 20px; margin: 10px 0; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
                .header {{ background: #2c3e50; color: white; padding: 20px; border-radius: 8px; margin-bottom: 20px; }}
                .stat-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 15px; }}
                .stat-box {{ background: #3498db; color: white; padding: 15px; border-radius: 5px; text-align: center; }}
                .stat-value {{ font-size: 2em; font-weight: bold; }}
                .stat-label {{ font-size: 0.9em; opacity: 0.9; }}
                table {{ width: 100%; border-collapse: collapse; }}
                th, td {{ padding: 8px; text-align: left; border-bottom: 1px solid #ddd; }}
                th {{ background-color: #34495e; color: white; }}
                .timestamp {{ color: #7f8c8d; font-size: 0.9em; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1>Heroes of History - Player Dashboard</h1>
                    <p>Player: {player_name} | Level: {player_level} | World: {world_id}</p>
                    <p class="timestamp">Generated: {timestamp}</p>
                </div>
                
                <div class="stat-grid">
                    <div class="stat-box">
                        <div class="stat-value">{total_power:,}</div>
                        <div class="stat-label">Total Power</div>
                    </div>
                    <div class="stat-box">
                        <div class="stat-value">{total_heroes}</div>
                        <div class="stat-label">Heroes</div>
                    </div>
                    <div class="stat-box">
                        <div class="stat-value">{total_cities}</div>
                        <div class="stat-label">Cities</div>
                    </div>
                    <div class="stat-box">
                        <div class="stat-value">{highest_hero_level}</div>
                        <div class="stat-label">Max Hero Level</div>
                    </div>
                </div>
                
                <div class="card">
                    <h2>Top Heroes</h2>
                    <table>
                        <tr>
                            <th>Name</th>
                            <th>Level</th>
                            <th>Stars</th>
                            <th>Power</th>
                        </tr>
                        {heroes_table}
                    </table>
                </div>
                
                <div class="card">
                    <h2>Resources</h2>
                    <table>
                        <tr>
                            <th>Resource</th>
                            <th>Amount</th>
                        </tr>
                        {resources_table}
                    </table>
                </div>
            </div>
        </body>
        </html>
        """

        # Generate heroes table rows
        heroes_rows = []
        for hero in sorted(analysis['heroes'], key=lambda x: x['level'], reverse=True)[:10]:
            heroes_rows.append(f"""
                <tr>
                    <td>{hero['name']}</td>
                    <td>{hero['level']}</td>
                    <td>{hero['stars']}★</td>
                    <td>{hero.get('power', 0):,}</td>
                </tr>
            """)
        
        # Generate resources table rows
        resources_rows = []
        for resource, amount in analysis['resources'].items():
            resources_rows.append(f"""
                <tr>
                    <td>{resource.title()}</td>
                    <td>{amount:,}</td>
                </tr>
            """)
        
        # Fill in the template
        html_content = html_template.format(
            player_name=analysis['player_info'].get('name', 'Unknown'),
            player_level=analysis['player_info'].get('level', 0),
            world_id=self.world_id,
            timestamp=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            total_power=analysis['player_info'].get('power', 0),
            total_heroes=analysis['statistics']['total_heroes'],
            total_cities=analysis['statistics']['total_cities'],
            highest_hero_level=analysis['statistics']['highest_hero_level'],
            heroes_table=''.join(heroes_rows),
            resources_table=''.join(resources_rows)
        )
        
        # Save dashboard
        dashboard_path = os.path.join(self.data_dir, 'analysis/dashboard.html')
        with open(dashboard_path, 'w', encoding='utf-8') as f:
            f.write(html_content)
        
        print(f"📊 Dashboard created: {dashboard_path}")
        
        return dashboard_path

def main():
    parser = argparse.ArgumentParser(description='Heroes of History - Local Data Analyzer')
    parser.add_argument('--world', default='un1', choices=['un1', 'zz1'], 
                       help='Game world (un1=main, zz1=beta)')
    parser.add_argument('--data-dir', default='hoh_local_data',
                       help='Directory to store data')
    parser.add_argument('--skip-download', action='store_true',
                       help='Skip download and use existing data')
    
    args = parser.parse_args()
    
    print("🎮 Heroes of History - Local Data Analyzer")
    print("=" * 60)
    print(f"World: {args.world}")
    print(f"Data directory: {args.data_dir}")
    print()
    
    # Create analyzer instance
    analyzer = HoHLocalAnalyzer(world_id=args.world, data_dir=args.data_dir)
    analyzer.setup_directories()
    
    try:
        if not args.skip_download:
            # Get credentials
            username = input("Username: ")
            password = getpass("Password: ")
            
            # Login and download data
            analyzer.login(username, password)
            analyzer.fetch_all_data()
        else:
            # Load existing data
            print("📂 Loading existing data...")
            analyzer.load_existing_data()
        
        # Analyze data
        analysis = analyzer.analyze_player_info()
        
        # Generate report
        report = analyzer.generate_report(analysis)
        
        # Additional analysis
        analyzer.analyze_heroes_detailed()
        analyzer.analyze_resources_over_time()
        analyzer.export_to_csv(analysis)
        analyzer.create_summary_dashboard(analysis)
        
        # Display summary
        print("\n" + "=" * 60)
        print("📊 ANALYSIS COMPLETE")
        print("=" * 60)
        print(f"✅ Player: {analysis['player_info'].get('name', 'Unknown')}")
        print(f"✅ Level: {analysis['player_info'].get('level', 0)}")
        print(f"✅ Heroes: {analysis['statistics']['total_heroes']}")
        print(f"✅ Cities: {analysis['statistics']['total_cities']}")
        print()
        print(f"📁 Data saved in: {os.path.abspath(args.data_dir)}")
        print(f"📄 Report: {os.path.join(args.data_dir, 'analysis/player_report.txt')}")
        print(f"📊 Analysis: {os.path.join(args.data_dir, 'analysis/player_analysis.json')}")
        print(f"🌐 Dashboard: {os.path.join(args.data_dir, 'analysis/dashboard.html')}")
        print(f"📈 CSV Exports: {os.path.join(args.data_dir, 'csv_exports/')}")
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    return 0

if __name__ == "__main__":
    exit(main())