"""Apply a named simulator preset from the command line (development/demo only).

Usage: python scripts/run_demo_scenario.py rising_landslide_indicators SNP-05 [AGM-03 ...]
       python scripts/run_demo_scenario.py --list
"""
import sys

import _bootstrap  # noqa: F401
from app.config import load_settings
from app.db import Database
from app.services import assessments, simulator

if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] == "--list":
        for k, v in simulator.PRESETS.items():
            print(f"{k:32} {v['description']}")
        sys.exit(0)
    settings = load_settings()
    if not settings.demo_endpoints_active:
        sys.exit("Demo scenarios are disabled in this configuration.")
    preset, sites = sys.argv[1], sys.argv[2:]
    db = Database(settings.database_url)
    with db.tx() as tx:
        sites = sites or [r["id"] for r in tx.all("SELECT id FROM sites ORDER BY id")]
        actor = tx.one("SELECT id, display_name, role FROM users WHERE role = 'admin' LIMIT 1")
        result = simulator.apply_scenario(tx, sites, preset, None, actor, name=f"CLI: {preset}")
        for site_id in sites:
            for a in assessments.run_site(tx, site_id, trigger=f"scenario:{result['scenario_id']}", actor=actor):
                print(f"{site_id:7} {a['hazard']:12} {a['risk_tier']:18} reliability={a['reliability']:9} [{a['data_origin']}]")
