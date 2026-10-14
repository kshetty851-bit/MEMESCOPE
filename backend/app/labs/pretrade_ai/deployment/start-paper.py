"""Run on the host after building the image. Does not restart existing services."""
import os
from pathlib import Path
import secrets
import subprocess


def run(args, **kwargs):
    return subprocess.run(args, check=True, text=True, **kwargs)


root = Path(__file__).resolve().parent.parent
credentials = root / '.paper.env'
if not credentials.exists():
    password = secrets.token_hex(32)
    sql = f'''
DO $$ BEGIN
 IF NOT EXISTS(SELECT FROM pg_roles WHERE rolname='pretrade_ai_reader') THEN
  CREATE ROLE pretrade_ai_reader LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
 END IF;
END $$;
ALTER ROLE pretrade_ai_reader PASSWORD '{password}';
ALTER ROLE pretrade_ai_reader SET default_transaction_read_only = on;
ALTER ROLE pretrade_ai_reader SET statement_timeout = '8s';
GRANT CONNECT ON DATABASE memescope TO pretrade_ai_reader;
GRANT USAGE ON SCHEMA public TO pretrade_ai_reader;
GRANT SELECT ON grad_migrations, grad_tokens, grad_postgrad_samples TO pretrade_ai_reader;
'''
    run(['docker', 'exec', '-i', 'memescope-postgres-1', 'sh', '-c',
         'PGPASSWORD="$POSTGRES_PASSWORD" psql -X -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1'],
        input=sql, stdout=subprocess.DEVNULL)
    fd = os.open(credentials, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as stream:
        stream.write(f'PRETRADE_READ_DSN=postgresql://pretrade_ai_reader:{password}@postgres:5432/memescope\n')
        stream.write('PRETRADE_STATE=/data/paper.sqlite3\n')
        stream.write('PRETRADE_AUTH_URL=http://backend:8000/api/v1/alpha/session\n')
run(['docker', 'volume', 'create', 'memescope_pretrade_paper'], stdout=subprocess.DEVNULL)
run(['docker', 'run', '--rm', '--user', '0', '--volume', 'memescope_pretrade_paper:/data',
     '--entrypoint', 'chown', 'memescope-pretrade-ai:20261014', '10001:10001', '/data'])
run(['docker', 'run', '-d', '--name', 'memescope-pretrade-ai', '--network', 'memescope_default',
     '--network-alias', 'pretrade-ai', '--restart', 'unless-stopped', '--read-only',
     '--tmpfs', '/tmp:rw,noexec,nosuid,size=32m', '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges',
     '--memory', '512m', '--cpus', '0.5', '--pids-limit', '64', '--env-file', str(credentials),
     '--volume', 'memescope_pretrade_paper:/data', 'memescope-pretrade-ai:20261014'])
print('Isolated paper service started; existing services were not restarted.')
