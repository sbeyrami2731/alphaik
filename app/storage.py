from __future__ import annotations
import hashlib, os, secrets, sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

BASE = Path(__file__).resolve().parent.parent
DATA_DIR = BASE / 'runtime'
UPLOAD_DIR = DATA_DIR / 'uploads'
DB_PATH = DATA_DIR / 'alphaik.db'
DATA_DIR.mkdir(exist_ok=True)
UPLOAD_DIR.mkdir(exist_ok=True)


def _db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute('PRAGMA foreign_keys=ON')
    return con


def _hash_password(password: str, salt: str | None = None) -> str:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), 200_000).hex()
    return f'{salt}${digest}'


def _verify(password: str, stored: str) -> bool:
    try:
        salt, digest = stored.split('$', 1)
        return secrets.compare_digest(_hash_password(password, salt).split('$',1)[1], digest)
    except Exception:
        return False


def init_db():
def init_db():
    username = os.getenv('ALPHAIK_ADMIN_USER', '').strip()
    password = os.getenv('ALPHAIK_ADMIN_PASSWORD', '')

    if not username or not password.strip():
        raise RuntimeError(
            'Administrator credentials must be configured'
        )

    with _db() as con:
    with _db() as con:
        con.executescript('''
        CREATE TABLE IF NOT EXISTS users(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS sessions(
            token TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS projects(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            code TEXT,
            client TEXT,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS uploads(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            filename TEXT NOT NULL,
            stored_path TEXT NOT NULL,
            uploaded_at TEXT NOT NULL,
            version_no INTEGER NOT NULL,
            analysis_json TEXT,
            status TEXT NOT NULL DEFAULT 'UPLOADED'
        );
        ''')
        row = con.execute('SELECT id FROM users LIMIT 1').fetchone()
        if not row:
            con.execute('INSERT INTO users(username,password_hash,created_at) VALUES (?,?,?)',
                        (username, _hash_password(password), _now()))


def _now():
    return datetime.now(timezone.utc).isoformat()


def login(username: str, password: str) -> str | None:
    with _db() as con:
        row = con.execute('SELECT * FROM users WHERE username=?', (username,)).fetchone()
        if not row or not _verify(password, row['password_hash']):
            return None
        token = secrets.token_urlsafe(32)
        con.execute('INSERT INTO sessions(token,user_id,created_at) VALUES (?,?,?)', (token,row['id'],_now()))
        return token


def user_for_token(token: str | None):
    if not token: return None
    with _db() as con:
        return con.execute('''SELECT u.id,u.username FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token=?''',(token,)).fetchone()


def create_project(name: str, code: str | None = None, client: str | None = None) -> dict[str,Any]:
    with _db() as con:
        cur = con.execute('INSERT INTO projects(name,code,client,created_at) VALUES (?,?,?,?)',(name,code,client,_now()))
        return get_project(cur.lastrowid)


def list_projects():
    with _db() as con:
        rows = con.execute('''
          SELECT p.*, COUNT(u.id) upload_count, MAX(u.uploaded_at) last_upload
          FROM projects p LEFT JOIN uploads u ON u.project_id=p.id
          GROUP BY p.id ORDER BY p.id DESC
        ''').fetchall()
        return [dict(r) for r in rows]


def get_project(project_id: int):
    with _db() as con:
        r=con.execute('SELECT * FROM projects WHERE id=?',(project_id,)).fetchone()
        return dict(r) if r else None


def next_version(project_id:int)->int:
    with _db() as con:
        r=con.execute('SELECT COALESCE(MAX(version_no),0)+1 n FROM uploads WHERE project_id=?',(project_id,)).fetchone()
        return int(r['n'])


def save_upload(project_id:int, filename:str, content:bytes, analysis_json:str)->dict[str,Any]:
    version=next_version(project_id)
    pdir=UPLOAD_DIR / str(project_id)
    pdir.mkdir(exist_ok=True)
    safe_name=f'U{version:03d}_{Path(filename).name}'
    path=pdir/safe_name
    path.write_bytes(content)
    with _db() as con:
        cur=con.execute('''INSERT INTO uploads(project_id,filename,stored_path,uploaded_at,version_no,analysis_json,status)
                           VALUES(?,?,?,?,?,?,?)''',(project_id,filename,str(path),_now(),version,analysis_json,'ANALYZED'))
        row=con.execute('SELECT * FROM uploads WHERE id=?',(cur.lastrowid,)).fetchone()
        return dict(row)


def list_uploads(project_id:int):
    with _db() as con:
        rows=con.execute('SELECT id,filename,uploaded_at,version_no,status FROM uploads WHERE project_id=? ORDER BY version_no DESC',(project_id,)).fetchall()
        return [dict(r) for r in rows]


def latest_analysis(project_id:int):
    import json
    with _db() as con:
        r=con.execute('SELECT * FROM uploads WHERE project_id=? AND analysis_json IS NOT NULL ORDER BY version_no DESC LIMIT 1',(project_id,)).fetchone()
        if not r: return None
        d=json.loads(r['analysis_json'])
        d['_upload']={'id':r['id'],'filename':r['filename'],'uploaded_at':r['uploaded_at'],'version_no':r['version_no']}
        return d
