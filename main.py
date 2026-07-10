from fastapi import FastAPI, HTTPException, Depends, BackgroundTasks, Request, Response, Query
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel, EmailStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import List, Optional, NewType, Tuple, Any
from datetime import datetime, timedelta
import jwt
import json
import sqlite3
import redis
import random
import smtplib
from email.mime.text import MIMEText

class Settings(BaseSettings):
    DB_NAME: str
    REDIS_HOST: str
    REDIS_PORT: int
    REDIS_DB: int
    
    SMTP_SERVER: str
    SMTP_PORT: int
    SMTP_USER: str
    SMTP_PASSWORD: str
    
    JWT_SECRET: str
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRATION_MINUTES: int = 60 * 24

    model_config = SettingsConfigDict(env_file=".env")

settings = Settings()

app = FastAPI(title="Grape API", description="노드 연결 프로그램(Grape) 및 노드 데이터, 인증 관리 API")

redis_client = redis.Redis(
    host=settings.REDIS_HOST, 
    port=settings.REDIS_PORT, 
    db=settings.REDIS_DB, 
    decode_responses=True
)

def create_access_token(data: dict) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=settings.JWT_EXPIRATION_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)

def get_current_user(request: Request) -> str:
    token = request.cookies.get("access_token")
    if not token:
        raise HTTPException(status_code=401, detail="Unauthorized: 인증 토큰이 필요합니다.")
    try:
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
        email: str = payload.get("sub")
        if email is None:
            raise HTTPException(status_code=401, detail="Unauthorized: 유효하지 않은 토큰입니다.")
        return email
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Unauthorized: 토큰이 만료되었습니다.")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Unauthorized: 유효하지 않은 토큰입니다.")

def init_db():
    with sqlite3.connect(settings.DB_NAME) as conn:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS users (
                email TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        conn.execute('''
            CREATE TABLE IF NOT EXISTS grapes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user TEXT,
                meta TEXT NOT NULL,
                nodes TEXT NOT NULL,
                raw TEXT NOT NULL,
                downloads INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        conn.execute('''
            CREATE TABLE IF NOT EXISTS node_data (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user TEXT,
                meta TEXT NOT NULL,
                type TEXT NOT NULL,
                inputs TEXT NOT NULL,
                outputs TEXT NOT NULL,
                source TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        conn.commit()

@app.on_event("startup")
def on_startup():
    init_db()
    try:
        redis_client.ping()
    except redis.ConnectionError:
        print("Redis 연결 실패")

def get_db():
    conn = sqlite3.connect(settings.DB_NAME)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()

class GrapeMeta(BaseModel):
    name: str
    description: str

NodeId = NewType('NodeId', int)
NodeDataId = NewType('NodeDataId', int)
NodeType = str

class Node(BaseModel):
    id: int
    name: NodeDataId
    sans: List[Tuple[str, str]]
    next: Optional[int] = None

GrapeId = NewType('GrapeId', int)

class Grape(BaseModel):
    id: GrapeId
    meta: GrapeMeta
    nodes: List[Node]
    raw: str

class GrapeCreateRequest(BaseModel):
    meta: GrapeMeta
    nodes: List[Node]
    raw: str

class NodeDataCreateRequest(BaseModel):
    meta: GrapeMeta
    type: NodeType
    inputs: List[str]
    outputs: List[str]
    source: str

class NodeDataResponseModel(BaseModel):
    meta: GrapeMeta
    type: NodeType
    inputs: List[str]
    outputs: List[str]

class NodeDataSourceResponseModel(BaseModel):
    source: str

class StandardResponse(BaseModel):
    ok: bool
    message: str

class GrapeResponse(StandardResponse):
    data: Optional[Grape] = None

class GrapesResponse(StandardResponse):
    data: List[Grape] = []

class NodeDataCreateResponse(StandardResponse):
    data: Optional[NodeDataId] = None

class NodeDataResponse(StandardResponse):
    data: Optional[NodeDataResponseModel] = None

class NodeDataSourceResponse(StandardResponse):
    data: Optional[NodeDataSourceResponseModel] = None

class NodeDataListResponse(StandardResponse):
    data: List[NodeDataResponseModel] = []

class EmailRequest(BaseModel):
    email: EmailStr

class SignupRequest(BaseModel):
    email: EmailStr
    code: str
    name: str

class LoginRequest(BaseModel):
    email: EmailStr
    code: str

def send_verification_email(email_to: str, code: str):
    msg = MIMEText(f"인증 번호는 [{code}] 입니다.\n해당 인증 번호는 3분 동안 유효합니다.")
    msg['Subject'] = 'Grape API 이메일 인증 번호'
    msg['From'] = settings.SMTP_USER
    msg['To'] = email_to
    try:
        with smtplib.SMTP(settings.SMTP_SERVER, settings.SMTP_PORT) as server:
            server.ehlo()
            server.starttls()
            server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
            server.send_message(msg)
    except Exception as e:
        print(f"이메일 발송 실패: {e}")

@app.post("/auth/send-code", response_model=StandardResponse)
def send_code(req: EmailRequest, background_tasks: BackgroundTasks):
    verification_code = str(random.randint(100000, 999999))
    redis_client.setex(name=req.email, time=180, value=verification_code)
    background_tasks.add_task(send_verification_email, req.email, verification_code)
    return {"ok": True, "message": "인증 번호 발송 완료"}

@app.post("/auth/signup", response_model=StandardResponse)
def signup(req: SignupRequest, response: Response, db: sqlite3.Connection = Depends(get_db)):
    existing_user = db.execute("SELECT email FROM users WHERE email = ?", (req.email,)).fetchone()
    if existing_user:
        return {"ok": False, "message": "이미 가입된 이메일입니다."}
        
    stored_code = redis_client.get(req.email)
    if not stored_code or stored_code != req.code:
        return {"ok": False, "message": "인증 실패 또는 만료된 코드입니다."}
    redis_client.delete(req.email)
    
    db.execute("INSERT INTO users (email, name) VALUES (?, ?)", (req.email, req.name))
    db.commit()
    
    access_token = create_access_token(data={"sub": req.email, "name": req.name})
    response.set_cookie(key="access_token", value=access_token, httponly=True)
    return {"ok": True, "message": "회원가입 성공"}

@app.post("/auth/login", response_model=StandardResponse)
def login(req: LoginRequest, response: Response, db: sqlite3.Connection = Depends(get_db)):
    user = db.execute("SELECT name FROM users WHERE email = ?", (req.email,)).fetchone()
    if not user:
        return {"ok": False, "message": "가입되지 않은 이메일입니다."}

    stored_code = redis_client.get(req.email)
    if not stored_code or stored_code != req.code:
        return {"ok": False, "message": "인증 실패 또는 만료된 코드입니다."}
    redis_client.delete(req.email)
    
    access_token = create_access_token(data={"sub": req.email, "name": user["name"]})
    response.set_cookie(key="access_token", value=access_token, httponly=True)
    return {"ok": True, "message": "로그인 성공"}

PAGE_SIZE = 10

@app.post("/grapes", response_model=StandardResponse)
def create_grape(req: GrapeCreateRequest, db: sqlite3.Connection = Depends(get_db), current_user: str = Depends(get_current_user)):
    for node in req.nodes:
        for s in node.sans:
            if len(s) != 2:
                raise HTTPException(status_code=422, detail="sans 데이터는 반드시 2개의 원소를 가져야 합니다.")

    meta_json = req.meta.model_dump_json()
    nodes_json = json.dumps([node.model_dump() for node in req.nodes])

    cursor = db.execute(
        "INSERT INTO grapes (user, meta, nodes, raw) VALUES (?, ?, ?, ?)",
        (current_user, meta_json, nodes_json, req.raw)
    )
    db.commit()
    return {"ok": True, "message": f"Grape 저장 성공 ({cursor.lastrowid})"}

@app.get("/grapes/{grape_id}", response_model=GrapeResponse)
def get_grape(grape_id: int, db: sqlite3.Connection = Depends(get_db)):
    row = db.execute("SELECT id, meta, nodes, raw FROM grapes WHERE id = ?", (grape_id,)).fetchone()
    if not row:
        return {"ok": False, "message": "Grape not found.", "data": None}
    
    return {
        "ok": True, "message": "Success",
        "data": {
            "id": row["id"],
            "meta": json.loads(row["meta"]),
            "nodes": json.loads(row["nodes"]),
            "raw": row["raw"]
        }
    }

@app.get("/grapes", response_model=GrapesResponse)
def get_grapes_list(
    page: int = Query(..., description="몇번째 패이지 요청인가?"),
    user: Optional[str] = Query(None, description="어떤 유저의 노드에 대한 요청인가?"),
    sort: Optional[int] = Query(None, description="정렬 방식 (0:오래된순, 1:최신순, 2:다운로드 적은순, 3:다운로드 많은순)"),
    db: sqlite3.Connection = Depends(get_db)
):
    offset = (max(1, page) - 1) * PAGE_SIZE
    
    query_parts = ["SELECT id, meta, nodes, raw FROM grapes"]
    conditions, params = [], []
    
    if user:
        conditions.append("user = ?")
        params.append(user)
    if conditions:
        query_parts.append("WHERE " + " AND ".join(conditions))
        
    sort_mapping = {0: "id ASC", 1: "id DESC", 2: "downloads ASC", 3: "downloads DESC"}
    order_by = sort_mapping.get(sort, "id DESC")
        
    query_parts.append(f"ORDER BY {order_by} LIMIT ? OFFSET ?")
    params.extend([PAGE_SIZE, offset])
    
    rows = db.execute(" ".join(query_parts), tuple(params)).fetchall()
    data = [{"id": r["id"], "meta": json.loads(r["meta"]), "nodes": json.loads(r["nodes"]), "raw": r["raw"]} for r in rows]
    return {"ok": True, "message": "Success", "data": data}

@app.post("/nodes", response_model=NodeDataCreateResponse)
def create_node(req: NodeDataCreateRequest, db: sqlite3.Connection = Depends(get_db), current_user: str = Depends(get_current_user)):
    meta_json = req.meta.model_dump_json()
    inputs_json = json.dumps(req.inputs)
    outputs_json = json.dumps(req.outputs)

    cursor = db.execute(
        "INSERT INTO node_data (user, meta, type, inputs, outputs, source) VALUES (?, ?, ?, ?, ?, ?)",
        (current_user, meta_json, req.type, inputs_json, outputs_json, req.source)
    )
    db.commit()
    return {"ok": True, "message": "Node 생성 완료", "data": cursor.lastrowid}

@app.get("/nodes/{nodeId}/data", response_model=NodeDataResponse)
def get_node_data(nodeId: int, db: sqlite3.Connection = Depends(get_db)):
    row = db.execute("SELECT meta, type, inputs, outputs FROM node_data WHERE id = ?", (nodeId,)).fetchone()
    if not row:
        return {"ok": False, "message": "해당 노드를 찾을 수 없습니다.", "data": None}
    
    return {
        "ok": True, "message": "Success",
        "data": {
            "meta": json.loads(row["meta"]),
            "type": row["type"],
            "inputs": json.loads(row["inputs"]),
            "outputs": json.loads(row["outputs"])
        }
    }

@app.get("/nodes/{nodeId}/source", response_model=NodeDataSourceResponse)
def get_node_source(nodeId: int, db: sqlite3.Connection = Depends(get_db)):
    row = db.execute("SELECT source FROM node_data WHERE id = ?", (nodeId,)).fetchone()
    if not row:
        return {"ok": False, "message": "해당 노드를 찾을 수 없습니다.", "data": None}
    
    return {
        "ok": True, "message": "Success",
        "data": {"source": row["source"]}
    }

@app.get("/nodes", response_model=NodeDataListResponse)
def get_nodes_list(
    page: int = Query(..., description="몇번째 패이지 요청인가?"),
    user: Optional[str] = Query(None, description="어떤 유저의 노드에 대한 요청인가?"),
    sort: Optional[int] = Query(None, description="정렬 방식 (0:오래된순, 1:최신순, 2:다운로드 적은순, 3:다운로드 많은순)"),
    db: sqlite3.Connection = Depends(get_db)
):
    offset = (max(1, page) - 1) * PAGE_SIZE
    
    query_parts = ["SELECT id, meta, type, inputs, outputs FROM node_data"]
    conditions, params = [], []
    
    if user:
        conditions.append("user = ?")
        params.append(user)
    if conditions:
        query_parts.append("WHERE " + " AND ".join(conditions))
        
    sort_mapping = {0: "id ASC", 1: "id DESC"}
    order_by = sort_mapping.get(sort, "id DESC")
        
    query_parts.append(f"ORDER BY {order_by} LIMIT ? OFFSET ?")
    params.extend([PAGE_SIZE, offset])
    
    rows = db.execute(" ".join(query_parts), tuple(params)).fetchall()
    data = [{
        "meta": json.loads(r["meta"]),
        "type": r["type"],
        "inputs": json.loads(r["inputs"]),
        "outputs": json.loads(r["outputs"])
    } for r in rows]
    
    return {"ok": True, "message": "Success", "data": data}