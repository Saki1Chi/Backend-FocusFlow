from pydantic import BaseModel, ConfigDict
from typing import Optional, List
from datetime import datetime


# ─── Category ─────────────────────────────────────────────────────────────────

class CategoryBase(BaseModel):
    name: str
    color: str = "#4A90E2"
    icon: str = "label"


class CategoryCreate(CategoryBase):
    pass


class CategoryUpdate(BaseModel):
    name: Optional[str] = None
    color: Optional[str] = None
    icon: Optional[str] = None


class CategoryResponse(CategoryBase):
    id: int
    created_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


# ─── Task ─────────────────────────────────────────────────────────────────────

class TaskBase(BaseModel):
    title: str
    description: str = ""
    date: str
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    status: int = 0
    mode: int = 0
    category_id: Optional[int] = None
    recurrence: Optional[str] = None
    is_carried_over: bool = False
    day_order: int = 0
    parent_id: Optional[str] = None
    is_recurring_parent: bool = False


class TaskCreate(TaskBase):
    id: str  # UUID provided by client or admin panel


class TaskUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    date: Optional[str] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    status: Optional[int] = None
    mode: Optional[int] = None
    category_id: Optional[int] = None
    recurrence: Optional[str] = None
    is_carried_over: Optional[bool] = None
    day_order: Optional[int] = None
    is_recurring_parent: Optional[bool] = None


class TaskResponse(TaskBase):
    id: str
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


# ─── Stats ────────────────────────────────────────────────────────────────────

class StatsResponse(BaseModel):
    total: int
    pending: int
    in_progress: int
    completed: int
    categories: int


# ─── Bulk sync ────────────────────────────────────────────────────────────────

class BulkSyncResult(BaseModel):
    created: int
    updated: int


# ─── User ─────────────────────────────────────────────────────────────────────

class UserCreate(BaseModel):
    username: str
    display_name: str
    email: Optional[str] = None
    avatar_emoji: str = "🧑"
    avatar_color: str = "#4A90E2"
    bio: str = ""
    password: str


class UserUpdate(BaseModel):
    display_name: Optional[str] = None
    email: Optional[str] = None
    avatar_emoji: Optional[str] = None
    avatar_color: Optional[str] = None
    bio: Optional[str] = None
    password: Optional[str] = None
    completed_blocks: Optional[int] = None
    current_streak: Optional[int] = None
    is_active: Optional[bool] = None


class UserResponse(BaseModel):
    id: int
    username: str
    display_name: str
    email: Optional[str] = None
    avatar_emoji: str
    avatar_color: str
    bio: str
    completed_blocks: int
    current_streak: int
    is_active: bool
    created_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    token: str
    user: UserResponse


# ─── Friendship ───────────────────────────────────────────────────────────────

class FriendshipCreate(BaseModel):
    receiver_username: str


class FriendshipResponse(BaseModel):
    id: int
    requester_id: int
    receiver_id: int
    status: str
    created_at: Optional[datetime] = None
    requester: Optional[UserResponse] = None
    receiver: Optional[UserResponse] = None

    model_config = ConfigDict(from_attributes=True)


# ─── Challenge ────────────────────────────────────────────────────────────────

class ChallengeCreate(BaseModel):
    title: str
    challenged_username: str
    type: str = "blocks"   # blocks | tasks
    target: int = 10
    start_date: str        # ISO date string (YYYY-MM-DD)
    end_date: str          # ISO date string (YYYY-MM-DD)


class ChallengeUpdate(BaseModel):
    status: Optional[str] = None
    challenger_progress: Optional[int] = None
    challenged_progress: Optional[int] = None


class ChallengeResponse(BaseModel):
    id: int
    title: str
    challenger_id: int
    challenged_id: int
    type: str
    target: int
    start_date: str
    end_date: str
    status: str
    challenger_progress: int
    challenged_progress: int
    winner_id: Optional[int] = None
    created_at: Optional[datetime] = None
    challenger: Optional[UserResponse] = None
    challenged: Optional[UserResponse] = None
    winner: Optional[UserResponse] = None

    model_config = ConfigDict(from_attributes=True)


# ─── ActivityLog ──────────────────────────────────────────────────────────────

class ActivityLogCreate(BaseModel):
    type: str              # task_completed | blocks_completed | challenge_won | streak_achieved | friend_added
    description: str
    data: Optional[str] = None   # JSON string for extra payload
    is_public: bool = True


class ActivityLogResponse(BaseModel):
    id: int
    user_id: int
    type: str
    description: str
    data: Optional[str] = None
    is_public: bool
    created_at: Optional[datetime] = None
    user: Optional[UserResponse] = None

    model_config = ConfigDict(from_attributes=True)
