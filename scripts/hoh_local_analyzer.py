#!/usr/bin/env python3
"""
Heroes of History - Local Data Analyzer
Full rewrite using startup.json (HeroPush-based data model)
"""

import os
import re
import uuid
import json
import base64
import requests
from datetime import datetime
from getpass import getpass
import argparse


# ============================================================
#  CONSTANTS
# ============================================================

JSON_CONTENT_TYPE = "application/json"
PROTOBUF_CONTENT_TYPE = "application/x-protobuf"

GAME_LOGIN_URL = "https://{subdomain}.heroesgame.com/api/login"
ACCOUNT_PLAY_URL = "https://{subdomain}.heroesofhistorygame.com/core/api/account/play"
STARTUP_API_URL = "https://{world_id}.heroesofhistorygame.com/game/startup"

# ============================================================
#  CLASS DEF: HoHLocalAnalyzer
# ============================================================

class HoHLocalAnalyzer:
    def __init__(self, world_id='un1', data_dir='hoh_local_data'):
        self.world_id = world_id
        self.data_dir = data_dir
        self.session_data = None
        self.is_beta = world_id.startswith('zz')

        # Will be filled after parsing startup.json
        self.startup = None
        self.messages = []

        # Parsed data (filled in SECTION 3)
        self.player_info = {}
        self.heroes = []
        self.decks = []
        self.equipment = {}
        self.relics = {}
        self.cities = []
        self.alliance_members = []
        self.alliance_cities = []

    # ------------------------------------------------------------
    #  Basic Headers
    # ------------------------------------------------------------

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

    # ------------------------------------------------------------
    #  Directory Setup
    # ------------------------------------------------------------

    def setup_directories(self):
        """
        Safely clean all subfolders without deleting the top-level directory.
        This avoids Windows/OneDrive 'Access Denied' errors.
        """
        import shutil

        # Ensure top-level exists
        os.makedirs(self.data_dir, exist_ok=True)

        subfolders = ["raw", "parsed", "analysis", "csv_exports"]

        for sub in subfolders:
            full = os.path.join(self.data_dir, sub)

            # If subfolder exists, delete only its contents
            if os.path.exists(full):
                for entry in os.listdir(full):
                    path = os.path.join(full, entry)

                    try:
                        if os.path.isfile(path) or os.path.islink(path):
                            os.unlink(path)
                        else:
                            shutil.rmtree(path)
                    except Exception:
                        pass  # ignore locked files
            
            # Re-create subfolder
            os.makedirs(full, exist_ok=True)

    # ------------------------------------------------------------
    #  Login
    # ------------------------------------------------------------

    def login(self, username, password):
        print("🔐 Logging in...")
        session = requests.Session()

        login_payload = {
            "username": username,
            "password": password,
            "useRememberMe": False
        }

        subdomain = "beta" if self.is_beta else "www"
        login_res = session.post(
            GAME_LOGIN_URL.format(subdomain=subdomain),
            headers=self.default_headers(),
            json=login_payload
        )
        login_res.raise_for_status()
        login_data = login_res.json()

        # Follow redirect to get client version
        redirect_res = session.get(login_data["redirectUrl"])
        redirect_res.raise_for_status()

        m = re.search(r'const\s+clientVersion\s*=\s*"([^"]+)"', redirect_res.text)
        if not m:
            raise Exception("Client version not found.")

        client_version = m.group(1)
        print(f"📌 Client version: {client_version}")

        # Establish session
        play_payload = {
            "createDeviceToken": False,
            "meta": {
                "clientVersion": client_version,
                "device": "browser",
                "deviceHardware": "browser",
                "deviceManufacturer": "none",
                "deviceName": "browser",
                "locale": "en_US",
                "networkType": "wlan",
                "operatingSystemName": "browser",
                "operatingSystemVersion": "1",
                "userAgent": "hoh-local-analyzer"
            },
            "network": "BROWSER_SESSION",
            "token": "",
            "worldId": None
        }

        subdomain2 = "zz0" if self.is_beta else "un0"

        play_res = session.post(
            ACCOUNT_PLAY_URL.format(subdomain=subdomain2),
            headers=self.default_headers(),
            json=play_payload
        )
        play_res.raise_for_status()
        self.session_data = play_res.json()
        self.session_data["clientVersion"] = client_version

        print("✅ Login successful!")

    # ------------------------------------------------------------
    #  Fetch Startup Data
    # ------------------------------------------------------------

    def fetch_startup(self):
        print("\n📥 Fetching startup.json...")

        url = STARTUP_API_URL.format(world_id=self.world_id)

        # PROTOBUF version (binary)
        bin_res = requests.post(url, headers=self.api_headers(PROTOBUF_CONTENT_TYPE))
        bin_res.raise_for_status()
        startup_bin = bin_res.content

        # JSON version
        json_res = requests.post(url, headers=self.api_headers(JSON_CONTENT_TYPE))
        json_res.raise_for_status()
        startup_json_text = json_res.text

        # Save both
        self._save_file("raw/startup.bin", startup_bin, binary=True)
        self._save_file("raw/startup.json", startup_json_text)

        # Parse JSON
        self.startup = json.loads(startup_json_text)
        if "rootContext" in self.startup and "messages" in self.startup["rootContext"]:
            self.messages = self.startup["rootContext"]["messages"]
        else:
            raise Exception("Startup JSON missing rootContext.messages")

        print("✅ Startup data loaded!")

    # ------------------------------------------------------------
    #  Internal File Save Helper
    # ------------------------------------------------------------

    def _save_file(self, relative_path, data, binary=False):
        full_path = os.path.join(self.data_dir, relative_path)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)

        if binary:
            with open(full_path, "wb") as f:
                f.write(data)
        else:
            with open(full_path, "w", encoding="utf-8") as f:
                if isinstance(data, str):
                    f.write(data)
                else:
                    f.write(json.dumps(data, indent=2, ensure_ascii=False))

    # ============================================================
    #  SECTION 2: MESSAGE CLASSIFIER
    # ============================================================

    def classify_startup_messages(self):
        """
        Identify all DTO message types inside startup.json rootContext.messages
        and store raw data for later processing.
        """

        # Raw storages
        self.raw_playerdto = None
        self.raw_heropush = None
        self.raw_equipment_lists = []
        self.raw_relic_lists = []
        self.raw_cities = []
        self.raw_alliance_members = None
        self.raw_alliance_cities = []

        print("\n🔍 Classifying startup messages...")

        for msg in self.messages:
            dto_type = msg.get("@type", "")

            # ------------------------------------------
            # PlayerDTO → This is YOUR PLAYER PROFILE
            # ------------------------------------------
            if dto_type.endswith("PlayerDTO"):
                # Only store player whose id matches your session account
                self.raw_playerdto = msg
                continue

            # ------------------------------------------
            # HeroPush → ALL HEROES + ALL DECKS
            # ------------------------------------------
            if dto_type.endswith("HeroPush"):
                self.raw_heropush = msg
                continue

            # ------------------------------------------
            # AllEquipmentUnitDataDTO → equipment
            # ------------------------------------------
            if dto_type.endswith("AllEquipmentUnitDataDTO"):
                # May appear multiple times
                if "allEquipment" in msg:
                    self.raw_equipment_lists.append(msg["allEquipment"])
                continue

            # ------------------------------------------
            # RelicUnitDataDTO → relics
            # ------------------------------------------
            if dto_type.endswith("RelicUnitDataDTO"):
                # Some relics may not contain hero reference → we attach later
                self.raw_relic_lists.append(msg)
                continue

            # ------------------------------------------
            # CityDTO → player's cities
            # ------------------------------------------
            if dto_type.endswith("CityDTO"):
                self.raw_cities.append(msg)
                continue

            # ------------------------------------------
            # AllianceMembersResponse → alliance roster
            # ------------------------------------------
            if dto_type.endswith("AllianceMembersResponse"):
                self.raw_alliance_members = msg
                continue

            # ------------------------------------------
            # AllianceCityDTO → alliance cities
            # ------------------------------------------
            if dto_type.endswith("AllianceCityDTO"):
                self.raw_alliance_cities.append(msg)
                continue

        print("✅ Message classification complete!")

    # ============================================================
    #  SECTION 2b: Build Master Tables (Patched)
    # ============================================================

    def build_master_tables(self):
        """
        Convert classified raw data into structured models:
          - Player info
          - Heroes (from HeroPush.unlocked)
          - Decks (from HeroPush.deck)
          - Equipment (AllEquipmentUnitDataDTO)
          - Relics (RelicUnitDataDTO)
          - Cities (from PlayerDTO.unlockedCities)  <-- FIXED
          - Alliance members (AllianceMembersResponse)
          - Alliance cities stored separately, not mixed with user cities
        """

        print("\n🧱 Building master data tables...")

        # ------------------------------------------------------------
        # 1. Player Profile
        # ------------------------------------------------------------
        if self.raw_playerdto:
            self.player_info = {
                "id": self.raw_playerdto.get("id"),
                "displayName": self.raw_playerdto.get("displayName"),
                "username": self.raw_playerdto.get("username"),
                "allianceId": self.raw_playerdto.get("allianceId"),
            }
        else:
            self.player_info = {
                "id": None,
                "displayName": None,
                "username": None,
                "allianceId": None,
            }

        # ------------------------------------------------------------
        # 2. Heroes (from HeroPush.unlocked)
        # ------------------------------------------------------------
        if not self.raw_heropush:
            raise Exception("No HeroPush message found! Cannot build hero list.")

        self.heroes = []
        unlocked = self.raw_heropush.get("unlocked", [])

        for h in unlocked:
            hero_id = h.get("heroDefinitionId")

            self.heroes.append({
                "heroDefinitionId": hero_id,
                "name": hero_id.replace("hero.", "") if hero_id else None,
                "level": h.get("level"),
                "ascensionLevel": h.get("ascensionLevel"),
                "abilityLevel": h.get("abilityLevel"),
                "awakeningLevel": h.get("awakeningLevel"),
                "abilityMasteryPoints": h.get("abilityMasteryPoints"),
                "unlockedAt": h.get("unlockedAt")
            })

        hero_set = {h["heroDefinitionId"] for h in self.heroes}

        # ------------------------------------------------------------
        # 3. Decks (from HeroPush.deck)
        # ------------------------------------------------------------
        self.decks = []
        deck_list = self.raw_heropush.get("deck", [])

        for d in deck_list:
            self.decks.append({
                "definitionId": d.get("definitionId"),
                "heroes": [hid.replace("hero.", "") for hid in d.get("heroDefinitionId", [])]
            })

        # ------------------------------------------------------------
        # 4. Equipment (from AllEquipmentUnitDataDTO)
        # ------------------------------------------------------------
        self.equipment = {}

        for equip_group in self.raw_equipment_lists:
            for eq in equip_group:
                hero_def = eq.get("equippedOnHeroDefinitionId")
                if hero_def and hero_def in hero_set:
                    hero_name = hero_def.replace("hero.", "")
                    if hero_name not in self.equipment:
                        self.equipment[hero_name] = []

                    self.equipment[hero_name].append({
                        "id": eq.get("id"),
                        "slot": eq.get("equipmentSlotTypeDefinitionId"),
                        "set": eq.get("equipmentSetDefinitionId"),
                        "rarity": eq.get("equipmentRarityDefinitionId"),
                        "level": eq.get("level"),
                        "mainAttribute": eq.get("mainAttribute"),
                        "subAttributes": eq.get("subAttributes", [])
                    })

        # ------------------------------------------------------------
        # 5. Relics (RelicUnitDataDTO)
        # ------------------------------------------------------------
        self.relics = {}

        for relic_entry in self.raw_relic_lists:
            relic_def = relic_entry.get("relicDefinitionId")
            level = relic_entry.get("level")
            age = relic_entry.get("ageDefinitionId")

            hero_def = None
            if "supportingUnit" in relic_entry:
                hero_def = relic_entry["supportingUnit"].get("definitionId")

            # Only attach relics belonging to heroes you own
            if hero_def and hero_def in hero_set:
                hero_name = hero_def.replace("hero.", "")
                if hero_name not in self.relics:
                    self.relics[hero_name] = []
                self.relics[hero_name].append({
                    "relicDefinitionId": relic_def,
                    "level": level,
                    "age": age
                })

        # ------------------------------------------------------------
        # 6. USER CITIES (from PlayerDTO.unlockedCities)  <-- FIXED
        # ------------------------------------------------------------
        self.cities = []

        unlocked_cities = []
        if self.raw_playerdto:
            unlocked_cities = self.raw_playerdto.get("unlockedCities", [])

        for c in unlocked_cities:
            self.cities.append({
                "id": c.get("id"),
                "definitionId": c.get("definitionId"),
                "placedBuildingAmounts": c.get("placedBuildingAmounts", {}),
                "buildingLimits": c.get("buildingLimits", {})
            })

        # ------------------------------------------------------------
        # 7. Alliance Members
        # ------------------------------------------------------------
        self.alliance_members = []

        if self.raw_alliance_members:
            for m in self.raw_alliance_members.get("members", []):
                self.alliance_members.append({
                    "id": m.get("playerId"),
                    "name": m.get("playerName"),
                    "level": m.get("level"),
                    "power": m.get("power"),
                    "age": m.get("ageDefinitionId")
                })

        # ------------------------------------------------------------
        # 8. Alliance Cities (kept separate, not mixed with user cities)
        # ------------------------------------------------------------
        self.alliance_cities = []
        for ac in self.raw_alliance_cities:
            self.alliance_cities.append({
                "id": ac.get("id"),
                "ownerId": ac.get("playerId"),
                "definitionId": ac.get("definitionId")
            })

        print("✅ Master tables built!  (Cities fixed)")
        
    # ============================================================
    #  SECTION 3: CSV EXPORTS
    # ============================================================

    def export_to_csv_all(self):
        """
        Export all structured data to CSV files.
        Files:
          - heroes.csv
          - equipment.csv
          - relics.csv
          - decks.csv
          - cities.csv
          - alliance_members.csv
        """
        csv_dir = os.path.join(self.data_dir, "csv_exports")
        os.makedirs(csv_dir, exist_ok=True)

        self._export_heroes_csv(csv_dir)
        self._export_equipment_csv(csv_dir)
        self._export_relics_csv(csv_dir)
        self._export_decks_csv(csv_dir)
        self._export_cities_csv(csv_dir)
        self._export_alliance_members_csv(csv_dir)

        print(f"📊 CSV export complete! Saved to: {csv_dir}")

    # ------------------------------------------------------------
    # HEROES CSV
    # ------------------------------------------------------------

    def _export_heroes_csv(self, csv_dir):
        import csv

        path = os.path.join(csv_dir, "heroes.csv")
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([
                "heroDefinitionId", "name", "level", "ascensionLevel",
                "awakeningLevel", "abilityLevel", "abilityMasteryPoints", "unlockedAt"
            ])
            for h in self.heroes:
                writer.writerow([
                    h.get("heroDefinitionId"),
                    h.get("name"),
                    h.get("level"),
                    h.get("ascensionLevel"),
                    h.get("awakeningLevel"),
                    h.get("abilityLevel"),
                    h.get("abilityMasteryPoints"),
                    h.get("unlockedAt"),
                ])

    # ------------------------------------------------------------
    # EQUIPMENT CSV
    # ------------------------------------------------------------

    def _export_equipment_csv(self, csv_dir):
        import csv

        path = os.path.join(csv_dir, "equipment.csv")
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)

            writer.writerow([
                "heroName", "equipmentId", "slot", "set", "rarity", "level",
                "mainAttribute_stat", "mainAttribute_value",
                "subAttributes"  # stored as JSON string for convenience
            ])

            for hero_name, items in self.equipment.items():
                for eq in items:
                    main_attr = eq.get("mainAttribute", {})
                    stat_boost = main_attr.get("statBoost", {})

                    main_stat = stat_boost.get("unitStatDefinitionId")
                    main_value = stat_boost.get("value")

                    # Subattributes as JSON
                    sub_json = json.dumps(eq.get("subAttributes", []), ensure_ascii=False)

                    writer.writerow([
                        hero_name,
                        eq.get("id"),
                        eq.get("slot"),
                        eq.get("set"),
                        eq.get("rarity"),
                        eq.get("level"),
                        main_stat,
                        main_value,
                        sub_json
                    ])

    # ------------------------------------------------------------
    # RELICS CSV
    # ------------------------------------------------------------

    def _export_relics_csv(self, csv_dir):
        import csv

        path = os.path.join(csv_dir, "relics.csv")
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["heroName", "relicDefinitionId", "level", "age"])

            for hero_name, relic_list in self.relics.items():
                for r in relic_list:
                    writer.writerow([
                        hero_name,
                        r.get("relicDefinitionId"),
                        r.get("level"),
                        r.get("age")
                    ])

    # ------------------------------------------------------------
    # DECKS CSV
    # ------------------------------------------------------------

    def _export_decks_csv(self, csv_dir):
        import csv

        path = os.path.join(csv_dir, "decks.csv")
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["definitionId", "heroes"])

            for d in self.decks:
                writer.writerow([
                    d.get("definitionId"),
                    ", ".join(d.get("heroes", []))
                ])

    # ------------------------------------------------------------
    # CITIES CSV
    # ------------------------------------------------------------

    def _export_cities_csv(self, csv_dir):
        import csv

        path = os.path.join(csv_dir, "cities.csv")
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)

            writer.writerow(["id", "definitionId", "level", "placedBuildingsJSON"])

            for c in self.cities:
                placed_json = json.dumps(
                    c.get("placedBuildingAmounts", {}),
                    ensure_ascii=False
                )
                writer.writerow([
                    c.get("id"),
                    c.get("definitionId"),
                    c.get("level"),
                    placed_json
                ])

    # ------------------------------------------------------------
    # ALLIANCE MEMBERS CSV
    # ------------------------------------------------------------

    def _export_alliance_members_csv(self, csv_dir):
        import csv

        path = os.path.join(csv_dir, "alliance_members.csv")
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)

            writer.writerow(["id", "name", "level", "power", "age"])

            for m in self.alliance_members:
                writer.writerow([
                    m.get("id"),
                    m.get("name"),
                    m.get("level"),
                    m.get("power"),
                    m.get("age")
                ])
                
    # ============================================================
    #  SECTION 4: FULL DASHBOARD HTML
    # ============================================================

    def _format_building_name(self, raw_key):
        """
        Convert a raw HoH building key like:
            building.Building_AgeOfTheFranks_Home_Small_2
        Into a readable format:
            AgeOfTheFranks – Home Small (Level 2)
        """

        # Strip the prefix
        key = raw_key.replace("building.Building_", "")

        # Split remaining name
        parts = key.split("_")
        if len(parts) < 4:
            # Unexpected format; return raw
            return raw_key

        era = parts[0]
        name = parts[1]
        variant = parts[2]
        level = parts[3]

        # Beautify pieces (optional cleanup)
        era = era.replace("AgeOfTheFranks", "Age of the Franks") \
                 .replace("FeudalAge", "Feudal Age") \
                 .replace("IberianEra", "Iberian Era") \
                 .replace("MinoanEra", "Minoan Era") \
                 .replace("ClassicGreece", "Classic Greece") \
                 .replace("BronzeAge", "Bronze Age") \
                 .replace("TreasureHunt", "Treasure Hunt")

        name = name.replace("Home", "Home") \
                   .replace("Workshop", "Workshop") \
                   .replace("Barracks", "Barracks") \
                   .replace("CultureSite", "Culture Site") \
                   .replace("Farm", "Farm") \
                   .replace("Special", "Special") \
                   .replace("Collectable", "Collectable") \
                   .replace("City", "City")

        variant = variant.replace("Small", "Small") \
                         .replace("Average", "Average") \
                         .replace("Moderate", "Moderate") \
                         .replace("Large", "Large") \
                         .replace("Compact", "Compact") \
                         .replace("Little", "Little")

        return f"{era} – {name} {variant} (Level {level})"

    def create_summary_dashboard(self):
        """
        Generate a full HTML dashboard containing:
          - Hero list
          - Equipment per hero
          - Relics per hero
          - Deck/team lists
          - Cities
          - Alliance members
          - Summary metrics
        """

        print("\n🌐 Generating full dashboard...")

        # ------------------------------------------------------------
        # Summary Calculations
        # ------------------------------------------------------------

        total_heroes = len(self.heroes)
        total_equipment_items = sum(len(eqs) for eqs in self.equipment.values())
        total_relics = sum(len(r) for r in self.relics.values())
        total_cities = len(self.cities)
        alliance_count = len(self.alliance_members)

        # Current Timestamp
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # Player Name
        player_name = self.player_info.get("displayName") or self.player_info.get("username") or "Unknown"
        alliance_id = self.player_info.get("allianceId")

        # ------------------------------------------------------------
        # Build Hero Table HTML
        # ------------------------------------------------------------
        hero_rows = []
        for h in sorted(self.heroes, key=lambda x: x["level"], reverse=True):
            hero_rows.append(f"""
                <tr>
                    <td>{h['name']}</td>
                    <td>{h['level']}</td>
                    <td>{h.get('ascensionLevel', '')}</td>
                    <td>{h.get('awakeningLevel', '')}</td>
                    <td>{h.get('abilityLevel', '')}</td>
                    <td>{h.get('abilityMasteryPoints', '')}</td>
                </tr>
            """)

        hero_table_html = "".join(hero_rows)

        # ------------------------------------------------------------
        # Build Equipment HTML
        # ------------------------------------------------------------
        equipment_sections = []

        for hero_name, eq_list in self.equipment.items():
            rows = []
            for eq in eq_list:
                main_attr = eq.get("mainAttribute", {})
                statboost = main_attr.get("statBoost", {})
                main_stat = statboost.get("unitStatDefinitionId")
                main_value = statboost.get("value")

                # Subattributes
                sub_list = []
                for s in eq.get("subAttributes", []):
                    stat = s.get("unitStatAttributeDefinitionId")
                    unlocked_at = s.get("unlockedAtLevel")
                    rolled = s.get("rolledValue")
                    sub_list.append(f"{stat} (unlock {unlocked_at}, rolled {rolled})")

                sub_text = "<br>".join(sub_list)

                rows.append(f"""
                    <tr>
                        <td>{eq.get("slot")}</td>
                        <td>{eq.get("set")}</td>
                        <td>{eq.get("rarity")}</td>
                        <td>{eq.get("level")}</td>
                        <td>{main_stat}</td>
                        <td>{main_value}</td>
                        <td>{sub_text}</td>
                    </tr>
                """)

            table_rows = "".join(rows)

            equipment_sections.append(f"""
                <h3>{hero_name}</h3>
                <table>
                    <tr>
                        <th>Slot</th>
                        <th>Set</th>
                        <th>Rarity</th>
                        <th>Level</th>
                        <th>Main Stat</th>
                        <th>Value</th>
                        <th>Subattributes</th>
                    </tr>
                    {table_rows}
                </table>
            """)

        equipment_html = "".join(equipment_sections)

        # ------------------------------------------------------------
        # Relics per hero
        # ------------------------------------------------------------
        relic_sections = []
        for hero_name, relic_list in self.relics.items():
            rows = []
            for r in relic_list:
                rows.append(f"""
                    <tr>
                        <td>{r.get("relicDefinitionId")}</td>
                        <td>{r.get("level")}</td>
                        <td>{r.get("age")}</td>
                    </tr>
                """)
            relic_rows = "".join(rows)

            relic_sections.append(f"""
                <h3>{hero_name}</h3>
                <table>
                    <tr>
                        <th>Relic</th>
                        <th>Level</th>
                        <th>Age</th>
                    </tr>
                    {relic_rows}
                </table>
            """)

        relic_html = "".join(relic_sections)

        # ------------------------------------------------------------
        # Decks
        # ------------------------------------------------------------
        deck_rows = []
        for d in self.decks:
            heroes_list = ", ".join(d.get("heroes", []))
            deck_rows.append(f"""
                <tr>
                    <td>{d.get("definitionId")}</td>
                    <td>{heroes_list}</td>
                </tr>
            """)

        decks_html = "".join(deck_rows)

        # ------------------------------------------------------------
        # Cities
        # ------------------------------------------------------------
        city_rows = []
        for c in self.cities:

            # ----------- Nicely formatted buildings -----------
            buildings = c.get("placedBuildingAmounts", {})
            building_lines = []

            for bkey, amount in buildings.items():
                pretty = self._format_building_name(bkey)
                building_lines.append(f"{pretty}: {amount}")

            buildings_html = "<br>".join(building_lines) if building_lines else "None"

            city_rows.append(f"""
                <tr>
                    <td>{c.get("id")}</td>
                    <td>{c.get("definitionId")}</td>
                    <td>{buildings_html}</td>
                </tr>
            """)

        cities_html = "".join(city_rows)

        # ------------------------------------------------------------
        # Alliance Members
        # ------------------------------------------------------------
        alliance_rows = []
        for m in self.alliance_members:
            alliance_rows.append(f"""
                <tr>
                    <td>{m.get("id")}</td>
                    <td>{m.get("name")}</td>
                    <td>{m.get("level")}</td>
                    <td>{m.get("power")}</td>
                    <td>{m.get("age")}</td>
                </tr>
            """)

        alliance_html = "".join(alliance_rows)

        # ------------------------------------------------------------
        # HTML TEMPLATE  (all braces escaped)
        # ------------------------------------------------------------

        html = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Heroes of History - Full Dashboard</title>
    <style>
        body {{ font-family: Arial, sans-serif; background-color: #f4f4f4; margin: 20px; }}
        h1 {{ color: #2c3e50; }}
        h2 {{ margin-top: 40px; color: #34495e; }}
        h3 {{ margin-top: 25px; color: #7f8c8d; }}
        table {{ width: 100%; border-collapse: collapse; margin-bottom: 30px; }}
        th {{ background-color: #2c3e50; color: white; padding: 8px; text-align: left; }}
        td {{ background-color: #ffffff; padding: 8px; border-bottom: 1px solid #ddd; }}
        .summary-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
            gap: 15px;
            margin-bottom: 30px;
        }}
        .summary-box {{
            background: #3498db;
            color: white;
            padding: 15px;
            border-radius: 6px;
            text-align: center;
        }}
        .label {{ font-size: 0.8em; opacity: 0.9; }}
        .value {{ font-size: 1.6em; font-weight: bold; }}
    </style>
</head>

<body>
    <h1>Heroes of History - Full Dashboard</h1>
    <p>Player: {player_name} | Alliance ID: {alliance_id} | Generated: {timestamp}</p>

    <div class="summary-grid">
        <div class="summary-box"><div class="value">{total_heroes}</div><div class="label">Heroes</div></div>
        <div class="summary-box"><div class="value">{total_equipment_items}</div><div class="label">Equipment Items</div></div>
        <div class="summary-box"><div class="value">{total_relics}</div><div class="label">Relics</div></div>
        <div class="summary-box"><div class="value">{total_cities}</div><div class="label">Cities</div></div>
        <div class="summary-box"><div class="value">{alliance_count}</div><div class="label">Alliance Members</div></div>
    </div>

    <h2>Hero List</h2>
    <table>
        <tr>
            <th>Hero</th>
            <th>Level</th>
            <th>Ascension</th>
            <th>Awakening</th>
            <th>Ability Level</th>
            <th>Mastery</th>
        </tr>
        {hero_table_html}
    </table>

    <h2>Equipment by Hero</h2>
    {equipment_html}

    <h2>Relics by Hero</h2>
    {relic_html}

    <h2>Hero Decks (Teams)</h2>
    <table>
        <tr>
            <th>Deck</th>
            <th>Heroes</th>
        </tr>
        {decks_html}
    </table>

    <h2>Cities</h2>
    <table>
        <tr>
            <th>ID</th>
            <th>DefinitionId</th>
            <th>Placed Buildings</th>
        </tr>
        {cities_html}
    </table>

    <h2>Alliance Members</h2>
    <table>
        <tr>
            <th>ID</th>
            <th>Name</th>
            <th>Level</th>
            <th>Power</th>
            <th>Age</th>
        </tr>
        {alliance_html}
    </table>

</body>
</html>
        """

        # ------------------------------------------------------------
        # Save HTML
        # ------------------------------------------------------------

        out_path = os.path.join(self.data_dir, "analysis", "dashboard.html")
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(html)

        print(f"🌐 Dashboard created: {out_path}")
        return out_path
    
    # ============================================================
    #  SECTION 5: JSON ANALYSIS EXPORT + PARSED DATA SAVE
    # ============================================================

    def export_analysis_json(self):
        """
        Produces a complete analysis JSON structure containing:
            - player info
            - heroes
            - equipment
            - relics
            - decks
            - cities
            - alliance members
            - alliance cities
            - timestamp
        Saves to: analysis/player_analysis.json
        """

        print("\n📝 Exporting analysis summary JSON...")

        analysis = {
            "timestamp": datetime.now().isoformat(),
            "player": self.player_info,
            "heroes": self.heroes,
            "equipment": self.equipment,
            "relics": self.relics,
            "decks": self.decks,
            "cities": self.cities,
            "allianceMembers": self.alliance_members,
            "allianceCities": self.alliance_cities,
        }

        path = os.path.join(self.data_dir, "analysis", "player_analysis.json")
        os.makedirs(os.path.dirname(path), exist_ok=True)

        with open(path, "w", encoding="utf-8") as f:
            json.dump(analysis, f, indent=2, ensure_ascii=False)

        print(f"📄 Analysis JSON written → {path}")
        return analysis

    # ------------------------------------------------------------
    # SAVE PARSED RAW DATA FOR DEBUGGING
    # ------------------------------------------------------------

    def save_parsed_data(self):
        """
        Save all parsed raw-message-derived data structures into parsed/ directory.
        This is useful for understanding startup.json structures and debugging.
        """

        print("\n💾 Saving parsed data structures...")

        base = os.path.join(self.data_dir, "parsed")
        os.makedirs(base, exist_ok=True)

        raw_bundle = {
            "playerDTO": self.raw_playerdto,
            "heroPush": self.raw_heropush,
            "equipment_rawLists": self.raw_equipment_lists,
            "relic_rawLists": self.raw_relic_lists,
            "cities_raw": self.raw_cities,
            "allianceMembers_raw": self.raw_alliance_members,
            "allianceCities_raw": self.raw_alliance_cities
        }

        # Save a single bundle file containing everything
        with open(os.path.join(base, "parsed_raw_bundle.json"), "w", encoding="utf-8") as f:
            json.dump(raw_bundle, f, indent=2, ensure_ascii=False)

        # Also save master tables for debugging
        master_bundle = {
            "player": self.player_info,
            "heroes": self.heroes,
            "decks": self.decks,
            "equipment": self.equipment,
            "relics": self.relics,
            "cities": self.cities,
            "allianceMembers": self.alliance_members,
            "allianceCities": self.alliance_cities
        }

        with open(os.path.join(base, "parsed_master_bundle.json"), "w", encoding="utf-8") as f:
            json.dump(master_bundle, f, indent=2, ensure_ascii=False)

        print("💾 Parsed data saved.")
        
# ============================================================
#  SECTION 6 — MAIN RUNNER
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="Heroes of History - Local Startup Analyzer")
    parser.add_argument("--world", default="un1", help="World to connect to (un1, zz1, etc.)")
    parser.add_argument("--data-dir", default="hoh_local_data", help="Directory for output files")
    parser.add_argument("--skip-download", action="store_true", help="Use existing startup.json without logging in")

    args = parser.parse_args()

    print("🎮 Heroes of History - Local Data Analyzer")
    print("=" * 60)
    print(f"World: {args.world}")
    print(f"Output directory: {args.data_dir}")
    print()

    analyzer = HoHLocalAnalyzer(world_id=args.world, data_dir=args.data_dir)
    analyzer.setup_directories()

    try:
        # ------------------------------------------------------------
        # LOGIN + FETCH STARTUP.JSON
        # ------------------------------------------------------------
        if not args.skip_download:
            username = input("Username: ")
            password = getpass("Password: ")

            analyzer.login(username, password)
            analyzer.fetch_startup()
        else:
            print("📂 Using existing startup.json...")
            startup_path = os.path.join(args.data_dir, "raw", "startup.json")
            if not os.path.exists(startup_path):
                raise Exception("startup.json not found — cannot skip download.")

            with open(startup_path, "r", encoding="utf-8") as f:
                analyzer.startup = json.load(f)

            analyzer.messages = analyzer.startup.get("rootContext", {}).get("messages", [])

        # ------------------------------------------------------------
        # PARSE STARTUP MESSAGES
        # ------------------------------------------------------------
        analyzer.classify_startup_messages()
        analyzer.build_master_tables()

        # Save raw parsed structures for debugging
        analyzer.save_parsed_data()

        # ------------------------------------------------------------
        # EXPORTS — JSON, CSV, DASHBOARD
        # ------------------------------------------------------------
        analysis_json = analyzer.export_analysis_json()
        analyzer.export_to_csv_all()
        dashboard_path = analyzer.create_summary_dashboard()

        # ------------------------------------------------------------
        # FINAL SUMMARY
        # ------------------------------------------------------------
        print("\n" + "=" * 60)
        print("📊 ANALYSIS COMPLETE")
        print("=" * 60)
        print(f"Player: {analysis_json['player'].get('displayName', 'Unknown')}")
        print(f"Heroes: {len(analysis_json['heroes'])}")
        print(f"Equipment items: {sum(len(v) for v in analysis_json['equipment'].values())}")
        print(f"Relics: {sum(len(v) for v in analysis_json['relics'].values())}")
        print(f"Cities: {len(analysis_json['cities'])}")
        print(f"Alliance members: {len(analysis_json['allianceMembers'])}")
        print()
        print(f"📁 Data directory: {os.path.abspath(args.data_dir)}")
        print(f"📄 Analysis JSON: {os.path.join(args.data_dir, 'analysis/player_analysis.json')}")
        print(f"🌐 Dashboard: {dashboard_path}")
        print(f"📊 CSV Exports: {os.path.join(args.data_dir, 'csv_exports')}")
        print()

        return 0

    except Exception as e:
        print("\n❌ Error:", str(e))
        import traceback
        traceback.print_exc()
        return 1


# ------------------------------------------------------------
# Script Entry Point
# ------------------------------------------------------------
if __name__ == "__main__":
    exit(main())