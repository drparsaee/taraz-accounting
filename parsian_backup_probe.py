"""Read-only header probe for an *owned copy* of a Parsian SQL Server backup.

No extraction, no authentication, no SQL queries, no restore and no source
mutation. Never interpret a TAPE signature as evidence that tables migrated.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path

MAX_BACKUP_BYTES = 50 * 1024**3


def identify_backup(path: str | Path) -> dict:
    p = Path(path)
    if p.is_symlink():
        raise ValueError('Symlinked backups must not be probed')
    if not p.is_file() or p.suffix.lower() != '.bak':
        raise ValueError('Select a regular .bak file')
    size = p.stat().st_size
    if size < 512 or size > MAX_BACKUP_BYTES:
        raise ValueError('Backup size outside safe inspection limits')
    with p.open('rb') as reader:
        signature = reader.read(16)
    if signature[:4] == b'TAPE':
        return {
            'format': 'sqlserver_media_backup',
            'signature': 'TAPE',
            'bytes': size,
            'canImportIntoMadar': False,
            'requires': ['verified isolated SQL Server restore',
                         'table/relationship/edition schema inventory',
                         'complete field-to-ledger mapping',
                         'accounting trial balance reconciliation',
                         'human review before atomic migration'],
            'note': 'The media header does not prove database/schema validity or import compatibility',
        }
    return {
        'format': 'unknown_backup',
        'signature': 'unsupported',
        'bytes': size,
        'canImportIntoMadar': False,
        'requires': ['format and schema evidence'],
        'note': 'No supported Parsian import parser for this format',
    }


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Read first 16 bytes of a backup; never restore or import it')
    parser.add_argument('file', type=Path)
    arguments = parser.parse_args()
    print(json.dumps(identify_backup(arguments.file), ensure_ascii=False, indent=2))
