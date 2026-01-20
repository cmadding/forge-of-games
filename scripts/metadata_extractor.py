import os
import json
from collections import defaultdict

# ============================================================
#  METADATA EXTRACTOR - SECTION 1/4
#  Loads unified_metadata.json and prepares for extraction.
# ============================================================

# EDIT THIS PATH IF NEEDED
UNIFIED_METADATA_PATH = os.path.join(
    os.path.dirname(__file__),
    "..",
    "src",
    "protos",
    "unified_metadata.json"
)

# OUTPUT FILE (Goes into the scripts folder)
OUTPUT_METADATA_PATH = os.path.join(
    os.path.dirname(__file__),
    "metadata.json"
)

def load_unified_metadata(path):
    """
    Loads the unified metadata JSON file produced from all .proto files.
    """
    if not os.path.exists(path):
        raise FileNotFoundError(f"Unified metadata file not found: {path}")

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if "files" not in data:
        raise ValueError("Unified metadata JSON missing expected 'files' key.")

    print(f"Loaded unified metadata from: {path}")
    print(f"Found {len(data['files'])} proto files.\n")
    return data["files"]


def init_metadata_container():
    """
    Creates the structure of the final metadata.json output.
    """
    return {
        "enums": {},          # all enums extracted
        "messages": {},       # all messages extracted
        "equipment": {},      # cleaned equipment metadata
        "heroes": {},         # cleaned hero metadata
        "buildings": {},      # cleaned building metadata
        "stats": {},          # stat definitions & formulas
        "relics": {},         # relic metadata
        "city": {},           # city definitions
        "research": {},       # tech tree metadata
        "proto_structure": {},# raw message & enum layout
    }

# ============================================================
#  METADATA EXTRACTOR - SECTION 2/4
#  Extracts all enums, messages, and raw proto structure.
# ============================================================

def extract_enums(proto_files, metadata):
    """
    Extracts every enum from unified_metadata.json.
    Stores them in metadata["enums"].
    """
    enums = {}

    for file in proto_files:
        for enum in file.get("enums", []):
            enum_name = enum["name"]
            values = {v["name"]: v["number"] for v in enum.get("values", [])}

            enums[enum_name] = {
                "file": file["path"],
                "values": values
            }

    metadata["enums"] = enums
    print(f"Extracted {len(enums)} enums.")
    return metadata


def extract_messages(proto_files, metadata):
    """
    Extracts message definitions (field → type mappings).
    These are raw proto messages, not cleaned metadata.
    Useful for debugging and deep analysis.
    """
    messages = {}

    for file in proto_files:
        for msg in file.get("messages", []):
            msg_name = msg["name"]
            fields = {}

            for f in msg.get("fields", []):
                fields[f["name"]] = {
                    "type": f.get("type"),
                    "number": f.get("number"),
                    "label": f.get("label", ""),
                    "options_raw": f.get("options_raw", "")
                }

            messages[msg_name] = {
                "file": file["path"],
                "fields": fields
            }

    metadata["messages"] = messages
    print(f"Extracted {len(messages)} messages.")
    return metadata


def extract_proto_structure(proto_files, metadata):
    """
    Stores the entire raw proto structure, grouped by file.
    This is a developer-friendly reference layer.
    """
    structure = {}

    for file in proto_files:
        structure[file["path"]] = {
            "messages": [msg["name"] for msg in file.get("messages", [])],
            "enums": [enum["name"] for enum in file.get("enums", [])]
        }

    metadata["proto_structure"] = structure
    print(f"Stored proto structure for {len(structure)} files.")
    return metadata

# ============================================================
#  METADATA EXTRACTOR - SECTION 3/4
#  Creates cleaned, organized metadata categories.
# ============================================================

def extract_equipment_metadata(messages, enums, metadata):
    """
    Extracts equipment slot types, rarity, sets, attributes, stat boosts
    from the EquipmentItemDto and related messages.
    """
    eq = {}

    # Extract all enums containing the word "equipment" or "rarity"
    rarity_enums = {k: v for k, v in enums.items()
                    if "Rarity" in k or "equipment_rarity" in k.lower()}

    slot_enums = {k: v for k, v in enums.items()
                  if "equipment" in k.lower() and "slot" in k.lower()}

    eq["rarities"] = rarity_enums
    eq["slot_types"] = slot_enums

    # Extract stat boost definitions
    if "StatBoostDto" in messages:
        eq["stat_boost_fields"] = messages["StatBoostDto"]["fields"]

    # Equipment item fields
    if "EquipmentItemDto" in messages:
        eq["equipment_item_fields"] = messages["EquipmentItemDto"]["fields"]

    metadata["equipment"] = eq
    print("Equipment metadata extracted.")
    return metadata


def extract_hero_metadata(messages, metadata):
    """
    Extracts hero-related definitions: class, rarity, type, color,
    stats, abilities, progression metadata.
    """
    heroes = {}

    # Pull known definitions
    hero_defs = [
        "HeroDefinitionDTO",
        "HeroUnitDefinitionDTO",
        "HeroUnitTypeDefinitionDTO",
        "HeroUnitStatDefinitionDTO",
        "HeroUnitRarityDefinitionDTO",
        "HeroUnitColorDefinitionDTO",
        "HeroAwakeningComponentDTO",
        "HeroBattleAbilityComponentDTO"
    ]

    for h in hero_defs:
        if h in messages:
            heroes[h] = messages[h]["fields"]

    metadata["heroes"] = heroes
    print("Hero metadata extracted.")
    return metadata


def extract_building_metadata(messages, metadata):
    """
    Extract cleaned building definitions from:
      BuildingDefinitionDTO
      BuildingCustomizationDefinitionDTO
      BuildingGroupDto
      CityDefinitionDTO
    """
    b = {}

    building_defs = [
        "BuildingDefinitionDTO",
        "BuildingCustomizationDefinitionDTO",
        "BuildingGroupDto",
        "CityDefinitionDTO"
    ]

    for bd in building_defs:
        if bd in messages:
            b[bd] = messages[bd]["fields"]

    # Also store building components that define category, size, production, etc.
    component_keys = [
        c for c in messages.keys()
        if "ComponentDTO" in c and "Building" in c
    ]
    b["building_components"] = component_keys

    metadata["buildings"] = b
    print("Building metadata extracted.")
    return metadata


def extract_city_metadata(messages, metadata):
    """
    Extracts city map, expansion, and entity metadata.
    """
    city_meta = {}

    city_types = [
        "CityMapEntityDto",
        "CityMapEntityProductionDto",
        "CityMapEntityUpgradeDto",
        "CityDefinitionDTO",
        "CityDTO",
        "OtherCityDTO",
        "ExpansionMapEntityDto",
        "ExpansionDefinitionDTO"
    ]

    for ct in city_types:
        if ct in messages:
            city_meta[ct] = messages[ct]["fields"]

    metadata["city"] = city_meta
    print("City metadata extracted.")
    return metadata


def extract_relic_metadata(messages, metadata):
    """
    Extracts relic definitions from relic DTOs.
    """
    relics = {}

    relic_defs = [
        "RelicDefinitionDTO",
        "RelicLevelDto",
        "RelicStatBoostDto",
        "PlayerRelicDto",
        "RelicUnitDataDTO"
    ]

    for r in relic_defs:
        if r in messages:
            relics[r] = messages[r]["fields"]

    metadata["relics"] = relics
    print("Relic metadata extracted.")
    return metadata


def extract_stat_metadata(messages, metadata):
    """
    Extract stat definitions, formulas, value types, hero base stats,
    unit stat definitions, and stat boost components.
    """
    stat = {}

    stat_related = [
        "StatBoostDto",
        "UnitStatDto",
        "HeroUnitStatDefinitionDTO",
        "HeroUnitStatFormulaDefinitionDTO",
        "HeroUnitStatValueDefinitionDTO",
        "HeroUnitStatFormulaDefinitionUnitRarityFactorsDto",
        "HeroUnitStatFormulaDefinitionFactorsDto",
    ]

    for s in stat_related:
        if s in messages:
            stat[s] = messages[s]["fields"]

    metadata["stats"] = stat
    print("Stat metadata extracted.")
    return metadata


def extract_research_metadata(messages, metadata):
    """
    Extracts tech tree, research components, requirements, rewards,
    and technology state metadata.
    """
    res = {}

    res_defs = [
        "TechnologyDefinitionDTO",
        "ResearchComponentDTO",
        "ResearchRequirementDTO",
        "ResearchRewardsDto",
        "ResearchDetailsDto",
        "ResearchStateDTO",
        "ResearchStateTechnologyDto",
    ]

    for r in res_defs:
        if r in messages:
            res[r] = messages[r]["fields"]

    metadata["research"] = res
    print("Research metadata extracted.")
    return metadata

# ============================================================
#  METADATA EXTRACTOR - SECTION 4/4
#  Main runner, assembly, and metadata.json writer.
# ============================================================

def run_full_extraction():
    print("=== Heroes of History Metadata Extractor ===")
    print("Loading unified metadata...\n")

    proto_files = load_unified_metadata(UNIFIED_METADATA_PATH)

    print("Initializing metadata container...\n")
    metadata = init_metadata_container()

    # ------------------------------
    # Stage 1: Raw structure extraction
    # ------------------------------
    messages = {}
    enums = {}

    metadata = extract_enums(proto_files, metadata)
    enums = metadata["enums"]

    metadata = extract_messages(proto_files, metadata)
    messages = metadata["messages"]

    metadata = extract_proto_structure(proto_files, metadata)

    # ------------------------------
    # Stage 2: Cleaned metadata
    # ------------------------------
    metadata = extract_equipment_metadata(messages, enums, metadata)
    metadata = extract_hero_metadata(messages, metadata)
    metadata = extract_building_metadata(messages, metadata)
    metadata = extract_city_metadata(messages, metadata)
    metadata = extract_relic_metadata(messages, metadata)
    metadata = extract_stat_metadata(messages, metadata)
    metadata = extract_research_metadata(messages, metadata)

    # ------------------------------
    # Save metadata.json
    # ------------------------------
    with open(OUTPUT_METADATA_PATH, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2, ensure_ascii=False)

    print("\n==============================================")
    print(f"Metadata extraction complete!")
    print(f"Saved output to: {OUTPUT_METADATA_PATH}")
    print("==============================================\n")


def main():
    try:
        run_full_extraction()
    except Exception as e:
        print("\n❌ ERROR during metadata extraction:")
        print(str(e))
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()