"""Export every schema, including accounts/progress, without printing secrets.

Run with the project's Python from the repository root. Needs PostgreSQL 16's
pg_dump in PATH (or PG_DUMP=/absolute/path/to/pg_dump). Keep the dump private.
"""
from datetime import datetime, timezone
from pathlib import Path
import os
import shutil
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import DatabaseConfig, load_dotenv


def main():
    load_dotenv()
    executable = os.environ.get('PG_DUMP') or shutil.which('pg_dump')
    if not executable:
        raise SystemExit('Install PostgreSQL 16 client tools or set PG_DUMP.')
    connection = DatabaseConfig.named(os.environ.get('DB_NAME', 'sentence_recommender')).dsn_kwargs()
    environment = os.environ.copy()
    for key, value in connection.items():
        variable = {'dbname': 'PGDATABASE', 'user': 'PGUSER', 'password': 'PGPASSWORD',
                    'host': 'PGHOST', 'port': 'PGPORT'}.get(key)
        if variable and value is not None:
            environment[variable] = str(value)
    # A schema-specific search_path is intentionally not applied: all schemas
    # must be restored, including accounts, corpus and each reader's state.
    folder = Path('dump')
    folder.mkdir(exist_ok=True)
    destination = folder / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ') + '.dump')
    try:
        with destination.open('xb') as output:
            destination.chmod(0o600)
            subprocess.run([executable, '--format=custom', '--no-owner'],
                           env=environment, stdout=output, check=True)
    except BaseException:
        destination.unlink(missing_ok=True)
        raise
    destination.chmod(0o600)
    print(f'Private full database backup: {destination}')


if __name__ == '__main__':
    main()
