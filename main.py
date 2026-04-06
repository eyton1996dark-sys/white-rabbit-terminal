from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, BackgroundTasks
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
import sqlite3
import json
import smtplib
import random
from email.mime.text import MIMEText
from datetime import datetime

app = FastAPI()

SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 465
SENDER_EMAIL = "harut.hayrapetyan2001@gmail.com"
SENDER_PASSWORD = "kltaaigwbxmjbovr"

def init_db():
    conn = sqlite3.connect("harutyun_db.sqlite")
    cursor = conn.cursor()
    # Создаем таблицы, если их нет
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            username TEXT UNIQUE NOT NULL,
            phone TEXT,
            dob TEXT,
            password TEXT NOT NULL
        )
    ''')
    # БЕЗОПАСНО ДОБАВЛЯЕМ КОЛОНКУ avatar ДЛЯ СТАРЫХ БАЗ ДАННЫХ
    try:
        cursor.execute("ALTER TABLE users ADD COLUMN avatar TEXT")
    except sqlite3.OperationalError:
        pass # Колонка уже существует, все ок

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS pending_users (
            email TEXT PRIMARY KEY,
            username TEXT UNIQUE NOT NULL,
            phone TEXT,
            dob TEXT,
            password TEXT NOT NULL,
            code TEXT NOT NULL
        )
    ''')
    cursor.execute('CREATE TABLE IF NOT EXISTS messages (id INTEGER PRIMARY KEY AUTOINCREMENT, sender TEXT, receiver TEXT, content TEXT, timestamp TEXT)')
    cursor.execute('CREATE TABLE IF NOT EXISTS contacts (id INTEGER PRIMARY KEY AUTOINCREMENT, owner TEXT, contact_name TEXT, UNIQUE(owner, contact_name))')
    conn.commit()
    conn.close()

init_db()

class UserRegister(BaseModel):
    email: str
    username: str
    phone: str
    dob: str
    password: str
    password_confirm: str

class UserLogin(BaseModel):
    email: str
    password: str

class VerifyCode(BaseModel):
    email: str
    code: str

class AvatarUpdate(BaseModel):
    username: str
    avatar_base64: str

def send_verification_email(to_email: str, code: str):
    try:
        msg = MIMEText(f"Ваш код для регистрации: {code}")
        msg['Subject'] = 'Код подтверждения'
        msg['From'] = SENDER_EMAIL
        msg['To'] = to_email
        with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT) as server:
            server.login(SENDER_EMAIL, SENDER_PASSWORD)
            server.send_message(msg)
    except Exception as e:
        print(f"Ошибка почты: {e}")

@app.post("/register")
async def register(user: UserRegister, background_tasks: BackgroundTasks):
    user.email = user.email.lower().strip()
    if user.password != user.password_confirm:
        raise HTTPException(status_code=400, detail="Пароли не совпадают!")
    
    conn = sqlite3.connect("harutyun_db.sqlite")
    cursor = conn.cursor()
    cursor.execute("SELECT email FROM users WHERE email=? OR username=?", (user.email, user.username))
    if cursor.fetchone():
        conn.close()
        raise HTTPException(status_code=400, detail="Email или Никнейм заняты!")

    code = str(random.randint(100000, 999999))
    cursor.execute("INSERT OR REPLACE INTO pending_users VALUES (?, ?, ?, ?, ?, ?)", 
                   (user.email, user.username, user.phone, user.dob, user.password, code))
    conn.commit()
    conn.close()
    background_tasks.add_task(send_verification_email, user.email, code)
    return {"message": "Код отправлен!"}

@app.post("/verify")
async def verify(data: VerifyCode):
    data.email = data.email.lower().strip()
    conn = sqlite3.connect("harutyun_db.sqlite")
    cursor = conn.cursor()
    cursor.execute("SELECT username, phone, dob, password, code FROM pending_users WHERE email=?", (data.email,))
    row = cursor.fetchone()
    if not row or data.code != row[4]:
        conn.close()
        raise HTTPException(status_code=400, detail="Неверный код!")
    
    try:
        cursor.execute("INSERT INTO users (email, username, phone, dob, password) VALUES (?, ?, ?, ?, ?)", 
                       (data.email, row[0], row[1], row[2], row[3]))
        cursor.execute("DELETE FROM pending_users WHERE email=?", (data.email,))
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        raise HTTPException(status_code=400, detail="Ошибка базы.")
    conn.close()
    return {"message": "Успех!"}

@app.post("/login")
async def login(user: UserLogin):
    user.email = user.email.lower().strip()
    conn = sqlite3.connect("harutyun_db.sqlite")
    cursor = conn.cursor()
    cursor.execute("SELECT username FROM users WHERE email=? AND password=?", (user.email, user.password))
    row = cursor.fetchone()
    conn.close()
    if row: return {"username": row[0]}
    raise HTTPException(status_code=400, detail="Неверный email или пароль")

@app.get("/get_profile/{username}")
async def get_profile(username: str):
    conn = sqlite3.connect("harutyun_db.sqlite")
    cursor = conn.cursor()
    cursor.execute("SELECT username, email, phone, dob, avatar FROM users WHERE username=?", (username,))
    row = cursor.fetchone()
    conn.close()
    if row:
        return {"username": row[0], "email": row[1], "phone": row[2], "dob": row[3], "avatar": row[4]}
    raise HTTPException(status_code=404, detail="User not found")

@app.post("/update_avatar")
async def update_avatar(data: AvatarUpdate):
    conn = sqlite3.connect("harutyun_db.sqlite")
    conn.execute("UPDATE users SET avatar=? WHERE username=?", (data.avatar_base64, data.username))
    conn.commit()
    conn.close()
    return {"ok": True}

@app.get("/search")
async def search(q: str):
    if not q: return []
    conn = sqlite3.connect("harutyun_db.sqlite")
    cursor = conn.cursor()
    cursor.execute("SELECT username, avatar FROM users WHERE LOWER(username) LIKE LOWER(?) LIMIT 10", (f"%{q}%",))
    users = [{"username": r[0], "avatar": r[1]} for r in cursor.fetchall()]
    conn.close()
    return users

@app.post("/add_contact")
async def add_contact(owner: str, contact: str):
    conn = sqlite3.connect("harutyun_db.sqlite")
    try:
        conn.execute("INSERT INTO contacts (owner, contact_name) VALUES (?, ?)", (owner, contact))
        conn.commit()
    except Exception as e:
        print("Ошибка добавления контакта:", e)
    finally:
        conn.close()
    return {"ok": True}

@app.get("/get_contacts/{username}")
async def get_contacts(username: str):
    conn = sqlite3.connect("harutyun_db.sqlite")
    cursor = conn.cursor()
    cursor.execute('''
        SELECT u.username, u.avatar 
        FROM contacts c 
        JOIN users u ON c.contact_name = u.username 
        WHERE c.owner=?
    ''', (username,))
    res = [{"username": r[0], "avatar": r[1]} for r in cursor.fetchall()]
    conn.close()
    return res

@app.get("/history/{u1}/{u2}")
async def get_history(u1: str, u2: str):
    conn = sqlite3.connect("harutyun_db.sqlite")
    cursor = conn.cursor()
    cursor.execute("SELECT sender, content, timestamp FROM messages WHERE (sender=? AND receiver=?) OR (sender=? AND receiver=?)", (u1, u2, u2, u1))
    res = [{"sender": r[0], "text": r[1], "time": r[2]} for r in cursor.fetchall()]
    conn.close()
    return res

@app.get("/")
async def get():
    with open("index.html", "r", encoding="utf-8") as f:
        return HTMLResponse(f.read())

class ConnectionManager:
    def __init__(self): self.active_connections = {}
    async def connect(self, ws, user):
        await ws.accept()
        self.active_connections[user] = ws
    def disconnect(self, user):
        if user in self.active_connections: del self.active_connections[user]
    async def send_to(self, msg, user):
        if user in self.active_connections: await self.active_connections[user].send_text(json.dumps(msg))

manager = ConnectionManager()

@app.websocket("/ws/{username}")
async def websocket_endpoint(websocket: WebSocket, username: str):
    await manager.connect(websocket, username)
    try:
        while True:
            data = await websocket.receive_text()
            msg = json.loads(data)
            dest = msg.get("to")
            text = msg.get("text")
            if dest and text:
                time = datetime.now().strftime("%H:%M")
                conn = sqlite3.connect("harutyun_db.sqlite")
                conn.execute("INSERT INTO messages (sender, receiver, content, timestamp) VALUES (?, ?, ?, ?)", (username, dest, text, time))
                conn.commit()
                conn.close()
                pkt = {"from": username, "text": text, "timestamp": time}
                await manager.send_to(pkt, dest)
                await websocket.send_text(json.dumps(pkt))
    except WebSocketDisconnect:
        manager.disconnect(username)
    except Exception:
        manager.disconnect(username)