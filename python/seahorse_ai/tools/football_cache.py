import json
import logging
import os

logger = logging.getLogger("football_cache")
CACHE_FILE = "/Users/weerachit/Documents/seahorse/football_cache.json"

def load_cache():
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE) as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load cache: {e}")
    return {"teams": {}, "fixtures": {}, "leagues": {}}

def save_cache(cache):
    try:
        with open(CACHE_FILE, "w") as f:
            json.dump(cache, f, indent=2)
    except Exception as e:
        logger.error(f"Failed to save cache: {e}")

def get_team_id(team_name):
    cache = load_cache()
    return cache["teams"].get(team_name.lower())

def set_team_id(team_name, team_id):
    cache = load_cache()
    cache["teams"][team_name.lower()] = team_id
    save_cache(cache)

def get_fixture_info(fixture_id):
    cache = load_cache()
    return cache["fixtures"].get(str(fixture_id))

def set_fixture_info(fixture_id, info):
    cache = load_cache()
    cache["fixtures"][str(fixture_id)] = info
    save_cache(cache)
