from fastapi import FastAPI, APIRouter, HTTPException, Depends, UploadFile, File, Form, Query
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
from google.cloud import storage
from pydantic import BaseModel, Field, EmailStr
from passlib.context import CryptContext
from jose import JWTError, jwt
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Dict, Any
from dotenv import load_dotenv
from pathlib import Path
import os
import uuid
import logging

# Load environment variables
ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# Security
SECRET_KEY = "your-secret-key-change-in-production"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30 * 24  # 30 days

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
security = HTTPBearer()

# MongoDB connection
mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

# Google Cloud Storage setup
os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = str(ROOT_DIR / 'gcs_credentials.json')
gcs_client = storage.Client()
bucket_name = "abc-music-library-files"
bucket = gcs_client.bucket(bucket_name)

app = FastAPI(title="ABC Music Library API")
api_router = APIRouter(prefix="/api")

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get('CORS_ORIGINS', '*').split(','),
    allow_methods=["*"],
    allow_headers=["*"],
)

# Models
class UserRole(str):
    ADMIN = "admin"
    TEACHER = "teacher"
    STUDENT = "student"

class User(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    email: EmailStr
    full_name: str
    role: str = UserRole.STUDENT
    avatar_url: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    is_active: bool = True

class UserCreate(BaseModel):
    email: EmailStr
    password: str
    full_name: str
    role: str = UserRole.STUDENT

class UserLogin(BaseModel):
    email: EmailStr
    password: str

class UserUpdate(BaseModel):
    full_name: Optional[str] = None
    avatar_url: Optional[str] = None

class Token(BaseModel):
    access_token: str
    token_type: str
    user: User

class SheetMusic(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    title: str
    composer: str
    genre: str
    difficulty_level: str  # beginner, intermediate, advanced
    description: Optional[str] = None
    pdf_url: Optional[str] = None
    audio_url: Optional[str] = None
    thumbnail_url: Optional[str] = None
    uploaded_by: str  # user_id
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    tags: List[str] = []
    is_published: bool = False

class SheetMusicCreate(BaseModel):
    title: str
    composer: str
    genre: str
    difficulty_level: str
    description: Optional[str] = None
    tags: List[str] = []

class Lesson(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    title: str
    description: str
    content: str  # HTML content
    category: str  # theory, harmony, rhythm, etc.
    difficulty_level: str
    created_by: str  # user_id
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    is_published: bool = False
    exercises: List[Dict[str, Any]] = []

class LessonCreate(BaseModel):
    title: str
    description: str
    content: str
    category: str
    difficulty_level: str
    exercises: List[Dict[str, Any]] = []

class UserProgress(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    user_id: str
    lesson_id: str
    completed: bool = False
    score: Optional[int] = None
    completed_at: Optional[datetime] = None
    attempts: int = 0

# Utility functions
def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password):
    return pwd_context.hash(password)

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    try:
        token = credentials.credentials
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: str = payload.get("sub")
        if user_id is None:
            raise HTTPException(status_code=401, detail="Invalid authentication credentials")
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid authentication credentials")
    
    user = await db.users.find_one({"id": user_id})
    if user is None:
        raise HTTPException(status_code=401, detail="User not found")
    
    return User(**user)

async def get_admin_user(current_user: User = Depends(get_current_user)):
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Admin access required")
    return current_user

async def get_teacher_or_admin(current_user: User = Depends(get_current_user)):
    if current_user.role not in [UserRole.TEACHER, UserRole.ADMIN]:
        raise HTTPException(status_code=403, detail="Teacher or admin access required")
    return current_user

def upload_file_to_gcs(file_content: bytes, filename: str, content_type: str) -> str:
    """Upload file to Google Cloud Storage and return public URL"""
    blob = bucket.blob(filename)
    blob.upload_from_string(file_content, content_type=content_type)
    blob.make_public()
    return blob.public_url

def generate_signed_url(filename: str, expiration_minutes: int = 60) -> str:
    """Generate signed URL for private file access"""
    blob = bucket.blob(filename)
    return blob.generate_signed_url(
        version="v4",
        expiration=timedelta(minutes=expiration_minutes),
        method="GET"
    )

# Auth endpoints
@api_router.post("/auth/register", response_model=Token)
async def register(user_data: UserCreate):
    # Check if user exists
    existing_user = await db.users.find_one({"email": user_data.email})
    if existing_user:
        raise HTTPException(status_code=400, detail="Email already registered")
    
    # Create user
    hashed_password = get_password_hash(user_data.password)
    user = User(
        email=user_data.email,
        full_name=user_data.full_name,
        role=user_data.role
    )
    
    user_dict = user.dict()
    user_dict["password"] = hashed_password
    
    await db.users.insert_one(user_dict)
    
    # Create token
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user.id}, expires_delta=access_token_expires
    )
    
    return Token(access_token=access_token, token_type="bearer", user=user)

@api_router.post("/auth/login", response_model=Token)
async def login(user_data: UserLogin):
    user = await db.users.find_one({"email": user_data.email})
    if not user or not verify_password(user_data.password, user["password"]):
        raise HTTPException(status_code=401, detail="Incorrect email or password")
    
    user_obj = User(**user)
    
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user_obj.id}, expires_delta=access_token_expires
    )
    
    return Token(access_token=access_token, token_type="bearer", user=user_obj)

@api_router.get("/auth/me", response_model=User)
async def get_current_user_info(current_user: User = Depends(get_current_user)):
    return current_user

# User endpoints
@api_router.put("/users/profile", response_model=User)
async def update_profile(
    user_update: UserUpdate,
    current_user: User = Depends(get_current_user)
):
    update_data = {k: v for k, v in user_update.dict().items() if v is not None}
    
    if update_data:
        await db.users.update_one(
            {"id": current_user.id},
            {"$set": update_data}
        )
    
    updated_user = await db.users.find_one({"id": current_user.id})
    return User(**updated_user)

# File upload endpoints
@api_router.post("/files/upload")
async def upload_file(
    file: UploadFile = File(...),
    file_type: str = Form(...),
    current_user: User = Depends(get_current_user)
):
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file provided")
    
    # Validate file type
    allowed_types = {
        "pdf": ["application/pdf"],
        "audio": ["audio/mpeg", "audio/mp3", "audio/wav"],
        "image": ["image/jpeg", "image/png", "image/webp"]
    }
    
    if file_type not in allowed_types:
        raise HTTPException(status_code=400, detail="Invalid file type")
    
    if file.content_type not in allowed_types[file_type]:
        raise HTTPException(status_code=400, detail=f"File must be of type {allowed_types[file_type]}")
    
    # Generate unique filename
    file_extension = file.filename.split('.')[-1]
    unique_filename = f"{current_user.id}_{uuid.uuid4()}_{int(datetime.now().timestamp())}.{file_extension}"
    
    # Read file content
    file_content = await file.read()
    
    # Upload to GCS
    try:
        file_url = upload_file_to_gcs(file_content, unique_filename, file.content_type)
        return {
            "filename": unique_filename,
            "url": file_url,
            "size": len(file_content),
            "content_type": file.content_type
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to upload file: {str(e)}")

# Sheet Music endpoints
@api_router.post("/sheet-music", response_model=SheetMusic)
async def create_sheet_music(
    sheet_music_data: SheetMusicCreate,
    current_user: User = Depends(get_teacher_or_admin)
):
    sheet_music = SheetMusic(
        **sheet_music_data.dict(),
        uploaded_by=current_user.id
    )
    
    sheet_music_dict = sheet_music.dict()
    await db.sheet_music.insert_one(sheet_music_dict)
    
    return sheet_music

@api_router.get("/sheet-music", response_model=List[SheetMusic])
async def get_sheet_music(
    genre: Optional[str] = None,
    difficulty: Optional[str] = None,
    search: Optional[str] = None,
    skip: int = 0,
    limit: int = 20,
    current_user: User = Depends(get_current_user)
):
    query = {"is_published": True}
    
    if genre:
        query["genre"] = genre
    if difficulty:
        query["difficulty_level"] = difficulty
    if search:
        query["$or"] = [
            {"title": {"$regex": search, "$options": "i"}},
            {"composer": {"$regex": search, "$options": "i"}}
        ]
    
    sheet_music = await db.sheet_music.find(query).skip(skip).limit(limit).to_list(None)
    return [SheetMusic(**sm) for sm in sheet_music]

@api_router.get("/sheet-music/{sheet_id}", response_model=SheetMusic)
async def get_sheet_music_by_id(
    sheet_id: str,
    current_user: User = Depends(get_current_user)
):
    sheet_music = await db.sheet_music.find_one({"id": sheet_id})
    if not sheet_music:
        raise HTTPException(status_code=404, detail="Sheet music not found")
    
    return SheetMusic(**sheet_music)

@api_router.put("/sheet-music/{sheet_id}", response_model=SheetMusic)
async def update_sheet_music(
    sheet_id: str,
    sheet_music_data: SheetMusicCreate,
    current_user: User = Depends(get_teacher_or_admin)
):
    sheet_music = await db.sheet_music.find_one({"id": sheet_id})
    if not sheet_music:
        raise HTTPException(status_code=404, detail="Sheet music not found")
    
    # Check if user owns the sheet music or is admin
    if sheet_music["uploaded_by"] != current_user.id and current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Not authorized to update this sheet music")
    
    update_data = sheet_music_data.dict()
    await db.sheet_music.update_one(
        {"id": sheet_id},
        {"$set": update_data}
    )
    
    updated_sheet_music = await db.sheet_music.find_one({"id": sheet_id})
    return SheetMusic(**updated_sheet_music)

# Lesson endpoints
@api_router.post("/lessons", response_model=Lesson)
async def create_lesson(
    lesson_data: LessonCreate,
    current_user: User = Depends(get_teacher_or_admin)
):
    lesson = Lesson(
        **lesson_data.dict(),
        created_by=current_user.id
    )
    
    lesson_dict = lesson.dict()
    await db.lessons.insert_one(lesson_dict)
    
    return lesson

@api_router.get("/lessons", response_model=List[Lesson])
async def get_lessons(
    category: Optional[str] = None,
    difficulty: Optional[str] = None,
    skip: int = 0,
    limit: int = 20,
    current_user: User = Depends(get_current_user)
):
    query = {"is_published": True}
    
    if category:
        query["category"] = category
    if difficulty:
        query["difficulty_level"] = difficulty
    
    lessons = await db.lessons.find(query).skip(skip).limit(limit).to_list(None)
    return [Lesson(**lesson) for lesson in lessons]

@api_router.get("/lessons/{lesson_id}", response_model=Lesson)
async def get_lesson_by_id(
    lesson_id: str,
    current_user: User = Depends(get_current_user)
):
    lesson = await db.lessons.find_one({"id": lesson_id})
    if not lesson:
        raise HTTPException(status_code=404, detail="Lesson not found")
    
    return Lesson(**lesson)

# Dashboard endpoints
@api_router.get("/dashboard/stats")
async def get_dashboard_stats(current_user: User = Depends(get_current_user)):
    # Get user's progress
    total_lessons = await db.lessons.count_documents({"is_published": True})
    completed_lessons = await db.user_progress.count_documents({
        "user_id": current_user.id,
        "completed": True
    })
    
    # Get recent sheet music
    recent_sheet_music = await db.sheet_music.find(
        {"is_published": True}
    ).sort("created_at", -1).limit(5).to_list(None)
    
    # Get recent lessons
    recent_lessons = await db.lessons.find(
        {"is_published": True}
    ).sort("created_at", -1).limit(5).to_list(None)
    
    return {
        "user": current_user,
        "stats": {
            "total_lessons": total_lessons,
            "completed_lessons": completed_lessons,
            "progress_percentage": (completed_lessons / total_lessons * 100) if total_lessons > 0 else 0
        },
        "recent_sheet_music": [SheetMusic(**sm) for sm in recent_sheet_music],
        "recent_lessons": [Lesson(**lesson) for lesson in recent_lessons]
    }

# Progress tracking
@api_router.post("/progress/{lesson_id}")
async def update_lesson_progress(
    lesson_id: str,
    completed: bool = True,
    score: Optional[int] = None,
    current_user: User = Depends(get_current_user)
):
    progress_data = {
        "user_id": current_user.id,
        "lesson_id": lesson_id,
        "completed": completed,
        "score": score,
        "completed_at": datetime.now(timezone.utc) if completed else None
    }
    
    existing_progress = await db.user_progress.find_one({
        "user_id": current_user.id,
        "lesson_id": lesson_id
    })
    
    if existing_progress:
        await db.user_progress.update_one(
            {"user_id": current_user.id, "lesson_id": lesson_id},
            {"$set": progress_data, "$inc": {"attempts": 1}}
        )
    else:
        progress = UserProgress(**progress_data)
        await db.user_progress.insert_one(progress.dict())
    
    return {"message": "Progress updated successfully"}

@api_router.get("/progress")
async def get_user_progress(current_user: User = Depends(get_current_user)):
    progress = await db.user_progress.find({"user_id": current_user.id}).to_list(None)
    return [UserProgress(**p) for p in progress]

# Include router
app.include_router(api_router)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()

@app.get("/")
async def root():
    return {"message": "ABC Music Library API"}