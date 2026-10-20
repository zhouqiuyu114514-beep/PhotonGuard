"""Explicit byte-bound evidence resolution; packet mode never uses host paths."""
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
import hashlib

@dataclass(frozen=True)
class ResolvedEvidence:
    path: Path
    original_receipt: dict

class EvidenceResolver:
    def __init__(self, packet_root=None, mapping=None):
        self.root = Path(packet_root).resolve() if packet_root is not None else None
        self.mapping = dict(mapping or {})
        if self.root is None and self.mapping:
            raise ValueError('MAPPING_REQUIRES_PACKET_ROOT')

    def resolve(self, entry):
        original = entry['path']
        if self.root is None:
            path = Path(original)
        else:
            if original not in self.mapping:
                raise ValueError('UNMAPPED_EVIDENCE:' + original)
            name = self.mapping[original]
            pure = PurePosixPath(name)
            if pure.is_absolute() or '..' in pure.parts or '\\' in name or ':' in name:
                raise ValueError('PATH_MAPPING_ESCAPE')
            path = (self.root / name).resolve()
            if not path.is_relative_to(self.root):
                raise ValueError('PATH_MAPPING_ESCAPE')
        if not path.is_file():
            raise ValueError('MISSING_EVIDENCE:' + original)
        if 'bytes' in entry and path.stat().st_size != entry['bytes']:
            raise ValueError('EVIDENCE_SIZE_MISMATCH:' + original)
        with path.open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        if digest != entry['sha256']:
            raise ValueError('EVIDENCE_HASH_MISMATCH:' + original)
        return ResolvedEvidence(path, dict(entry))

def resolve_evidence(entry, packet_root=None, mapping=None):
    return EvidenceResolver(packet_root, mapping).resolve(entry)
