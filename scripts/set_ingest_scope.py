"""Show or set which sites a push source (gateway) may write readings for.

Usage:
  python scripts/set_ingest_scope.py FIELD-GATEWAY-01                 # show the current scope
  python scripts/set_ingest_scope.py FIELD-GATEWAY-01 AGM-03 SNP-05   # allow only these sites
  python scripts/set_ingest_scope.py FIELD-GATEWAY-01 --none          # allow no sites
The change is recorded in the audit log.
"""
import argparse
import json
import sys

import _bootstrap  # noqa: F401
from app.config import load_settings
from app.db import Database
from app.services import audit

SCRIPT_ACTOR = {"id": None, "display_name": "set_ingest_scope.py (operator CLI)", "role": "admin_cli"}


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("source_id")
    p.add_argument("site_ids", nargs="*")
    p.add_argument("--none", action="store_true", help="remove all sites from the scope")
    args = p.parse_args(argv)
    db = Database(load_settings().database_url)
    db.migrate()
    with db.tx() as tx:
        src = tx.one("SELECT id, access_mode, ingest_site_scope FROM data_sources WHERE id = ?", (args.source_id,))
        if not src or src["access_mode"] != "push_api":
            print(f"'{args.source_id}' is not a push source.", file=sys.stderr)
            return 2
        current = json.loads(src["ingest_site_scope"]) if src["ingest_site_scope"] else []
        if not args.site_ids and not args.none:
            print(f"{args.source_id} may write to: {', '.join(current) or '(no sites)'}")
            return 0
        known = {r["id"] for r in tx.all("SELECT id FROM sites")}
        unknown = sorted(set(args.site_ids) - known)
        if unknown:
            print(f"Unknown site id(s): {', '.join(unknown)}", file=sys.stderr)
            return 2
        new = [] if args.none else sorted(set(args.site_ids))
        tx.execute("UPDATE data_sources SET ingest_site_scope = ? WHERE id = ?", (json.dumps(new), args.source_id))
        audit.record(tx, "data_source.scope_changed", "data_source", args.source_id,
                     {"before": current, "after": new}, SCRIPT_ACTOR)
    print(f"{args.source_id} may now write to: {', '.join(new) or '(no sites)'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
