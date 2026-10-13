"""Explicit paper-ledger migration. Preview by default; never rewrites holdings."""
import argparse
import json
import sqlite3
import sys
import uuid
from contextlib import closing
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from research_contracts import ENGINE_VERSION, RUNTIME_DIR


def migrate(path, apply=False):
    path = Path(path)
    if not path.exists():
        return {'status': 'no_database', 'legacy_count': 0}
    with closing(sqlite3.connect(path)) as conn:
        rows = conn.execute('SELECT strategy_id,state FROM accounts_v2').fetchall()
        legacy = [(key,state) for key,state in rows if '@' not in key and json.loads(state).get('engine_version','daily-v2') != ENGINE_VERSION]
        if not apply or not legacy:
            return {'status': 'preview', 'legacy_count': len(legacy)}
        stamp = datetime.now().strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex[:8]
        backup = path.parent / 'backups' / f'{path.stem}-{stamp}.db'
        backup.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(backup)) as destination:
            conn.backup(destination)
        with conn:
            conn.execute('BEGIN IMMEDIATE')
            for key,state in legacy:
                # A concurrent update must not be silently archived under an old decision.
                changed = conn.execute('UPDATE accounts_v2 SET strategy_id=?,name=name || ? WHERE strategy_id=? AND state=?',
                    (f'{key}@engine-archive@{stamp}', '（旧引擎归档）', key, state)).rowcount
                if changed != 1:
                    raise RuntimeError('账户在迁移期间发生变化；已回滚，请停止服务后重试。')
        return {'status': 'archived', 'legacy_count': len(legacy), 'backup': str(backup)}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true', help='Back up and archive old engines; next daily execution creates fresh accounts.')
    parser.add_argument('--database', type=Path, default=RUNTIME_DIR / 'virtual_v2.db')
    args = parser.parse_args()
    print(json.dumps(migrate(args.database, args.apply), ensure_ascii=False))
