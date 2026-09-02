from pathlib import Path
import json
from fastapi import FastAPI, UploadFile, File, HTTPException, Header
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from .analyzer import parse_workbook, analyze
from . import storage

BASE = Path(__file__).resolve().parent
app = FastAPI(title='Alphaik Project Controls', version='0.2.0')
app.mount('/static', StaticFiles(directory=BASE / 'static'), name='static')

@app.on_event('startup')
def startup(): storage.init_db()

@app.get('/')
def home(): return FileResponse(BASE / 'static' / 'index.html')

@app.get('/api/health')
def health(): return {'status':'ok','service':'alphaik','version':'0.2.0'}

class LoginIn(BaseModel): username:str; password:str
class ProjectIn(BaseModel): name:str; code:str|None=None; client:str|None=None

def auth(authorization: str | None):
    token = authorization.removeprefix('Bearer ').strip() if authorization else None
    user=storage.user_for_token(token)
    if not user: raise HTTPException(401,'Authentication required')
    return user

@app.post('/api/login')
def api_login(body:LoginIn):
    token=storage.login(body.username,body.password)
    if not token: raise HTTPException(401,'Invalid username or password')
    return {'token':token,'username':body.username}

@app.get('/api/projects')
def projects(authorization:str|None=Header(None)):
    auth(authorization); return storage.list_projects()

@app.post('/api/projects')
def project_create(body:ProjectIn, authorization:str|None=Header(None)):
    auth(authorization); return storage.create_project(body.name,body.code,body.client)

@app.get('/api/projects/{project_id}')
def project(project_id:int, authorization:str|None=Header(None)):
    auth(authorization); p=storage.get_project(project_id)
    if not p: raise HTTPException(404,'Project not found')
    p['uploads']=storage.list_uploads(project_id)
    p['latest_analysis']=storage.latest_analysis(project_id)
    return p

@app.post('/api/projects/{project_id}/upload')
async def project_upload(project_id:int, file:UploadFile=File(...), authorization:str|None=Header(None)):
    auth(authorization)
    if not storage.get_project(project_id): raise HTTPException(404,'Project not found')
    if not file.filename.lower().endswith('.xlsx'): raise HTTPException(400,'Current MVP accepts P6 Excel .xlsx exports.')
    try:
        content=await file.read(); task,rel=parse_workbook(content); result=analyze(task,rel); result['file_name']=file.filename
        up=storage.save_upload(project_id,file.filename,content,json.dumps(result,ensure_ascii=False,default=str))
        result['_upload']={'id':up['id'],'version_no':up['version_no'],'uploaded_at':up['uploaded_at']}
        return result
    except ValueError as exc: raise HTTPException(400,str(exc))
    except Exception as exc: raise HTTPException(500,f'Analysis failed: {exc}')
