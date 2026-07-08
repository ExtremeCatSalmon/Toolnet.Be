from fastapi import FastAPI, HTTPException, Depends
from pydantic import BaseModel
from typing import List, Optional
import json
import sqlite3

app = FastAPI(title="Grape API", description="노드를 연결하여 만든 프로그램(Grape) 관리 API")

DB_NAME = "Grape.db"

def init_db():
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS grapes (
                id INTEGER PRIMARY KEY,
                data TEXT NOT NULL
            )
        ''')
        conn.commit()

@app.on_event("startup")
def on_startup():
    init_db()

def get_db():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()

class Node(BaseModel):
    id: int
    inputs: List[str]
    outputs: List[str]
    next: Optional[int] = None

class Grape(BaseModel):
    id: int
    root: List[Node]
    raw: str

class StandardResponse(BaseModel):
    ok: bool
    message: str

class GrapeResponse(StandardResponse):
    grape: Optional[Grape] = None

class GrapesResponse(StandardResponse):
    grapes: List[Grape]

PAGE_SIZE = 5


@app.post("/grapes", response_model=StandardResponse)
def create_grape(grape: Grape, db: sqlite3.Connection = Depends(get_db)):
    grape_json_str = grape.model_dump_json()
    
    try:
        db.execute(
            "REPLACE INTO grapes (id, data) VALUES (?, ?)",
            (grape.id, grape_json_str)
        )
        db.commit()
        return {"ok": True, "message": f"Grape {grape.id} saved successfully."}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")


@app.get("/grapes/{grape_id}", response_model=GrapeResponse)
def get_grape(grape_id: int, db: sqlite3.Connection = Depends(get_db)):
    cursor = db.execute("SELECT data FROM grapes WHERE id = ?", (grape_id,))
    row = cursor.fetchone()
    
    if not row:
        return {"ok": False, "message": "Grape not found.", "grape": None}
    
    grape_data = json.loads(row["data"])
    return {"ok": True, "message": "Success", "grape": grape_data}