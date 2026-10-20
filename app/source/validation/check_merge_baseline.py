"""Read-only per-file preimage check; does not apply, overwrite, or inspect secrets."""
import hashlib
import json
from pathlib import Path
import sys

root = Path(__file__).resolve().parents[1]
target = Path(sys.argv[1]).resolve()
manifest = json.loads((root / 'delivery/changes.json').read_text(encoding='utf-8'))
conflicts = []
for entry in manifest:
    p = target / entry['path']
    if p.is_symlink() or any(parent.is_symlink() for parent in p.parents):
        conflicts.append({'path': entry['path'], 'reason': 'symlink target refused'}); continue
    if entry['old_sha256'] is None:
        if p.exists(): conflicts.append({'path': entry['path'], 'reason': 'new-file path already exists'})
    elif not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest() != entry['old_sha256']:
        conflicts.append({'path': entry['path'], 'reason': 'missing or differs from reviewed baseline'})
print(json.dumps({'target': str(target), 'preimages_match': not conflicts, 'conflicts': conflicts,
                  'files_written': 0, 'whole_checkout_clean_verified': False}, ensure_ascii=True, indent=2))
sys.exit(bool(conflicts))
