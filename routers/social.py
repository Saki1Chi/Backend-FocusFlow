from datetime import date as date_type
from typing import List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy.orm import Session

from database import get_db
import models
import schemas
from routers.users import get_current_user

router = APIRouter()


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _user_dict(user: models.User) -> dict:
    return schemas.UserResponse.model_validate(user).model_dump() if user else None


def _enrich_friendship(f: models.Friendship, db: Session) -> dict:
    return {
        "id": f.id,
        "requester_id": f.requester_id,
        "receiver_id": f.receiver_id,
        "status": f.status,
        "created_at": f.created_at,
        "requester": _user_dict(db.query(models.User).get(f.requester_id)),
        "receiver": _user_dict(db.query(models.User).get(f.receiver_id)),
    }


def _enrich_challenge(c: models.Challenge, db: Session) -> dict:
    return {
        "id": c.id,
        "title": c.title,
        "challenger_id": c.challenger_id,
        "challenged_id": c.challenged_id,
        "type": c.type,
        "target": c.target,
        "start_date": c.start_date,
        "end_date": c.end_date,
        "status": c.status,
        "challenger_progress": c.challenger_progress,
        "challenged_progress": c.challenged_progress,
        "winner_id": c.winner_id,
        "created_at": c.created_at,
        "challenger": _user_dict(db.query(models.User).get(c.challenger_id)),
        "challenged": _user_dict(db.query(models.User).get(c.challenged_id)),
        "winner": _user_dict(db.query(models.User).get(c.winner_id)) if c.winner_id else None,
    }


def _enrich_log(log: models.ActivityLog, db: Session) -> dict:
    return {
        "id": log.id,
        "user_id": log.user_id,
        "type": log.type,
        "description": log.description,
        "data": log.data,
        "is_public": log.is_public,
        "created_at": log.created_at,
        "user": _user_dict(db.query(models.User).get(log.user_id)),
    }


def _check_challenge_winner(challenge: models.Challenge) -> None:
    """Auto-complete a challenge when someone reaches the target."""
    if challenge.status != "active":
        return
    ch_done = challenge.challenger_progress >= challenge.target
    cd_done = challenge.challenged_progress >= challenge.target
    if ch_done or cd_done:
        challenge.status = "completed"
        if ch_done and cd_done:
            challenge.winner_id = None  # tie
        elif ch_done:
            challenge.winner_id = challenge.challenger_id
        else:
            challenge.winner_id = challenge.challenged_id


# ─── Friends (authenticated — mobile app) ────────────────────────────────────

@router.get("/friends", response_model=List[schemas.FriendshipResponse])
def list_my_friends(
    x_token: Optional[str] = Header(None),
    db: Session = Depends(get_db),
):
    me = get_current_user(x_token, db)
    rows = db.query(models.Friendship).filter(
        (models.Friendship.requester_id == me.id) |
        (models.Friendship.receiver_id == me.id)
    ).all()
    return [_enrich_friendship(f, db) for f in rows]


@router.post("/friends/request", response_model=schemas.FriendshipResponse)
def send_friend_request(
    data: schemas.FriendshipCreate,
    x_token: Optional[str] = Header(None),
    db: Session = Depends(get_db),
):
    me = get_current_user(x_token, db)
    receiver = db.query(models.User).filter(models.User.username == data.receiver_username).first()
    if not receiver:
        raise HTTPException(status_code=404, detail="User not found")
    if receiver.id == me.id:
        raise HTTPException(status_code=400, detail="Cannot add yourself")
    existing = db.query(models.Friendship).filter(
        ((models.Friendship.requester_id == me.id) & (models.Friendship.receiver_id == receiver.id)) |
        ((models.Friendship.requester_id == receiver.id) & (models.Friendship.receiver_id == me.id))
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="Friendship already exists")
    f = models.Friendship(requester_id=me.id, receiver_id=receiver.id)
    db.add(f)
    db.commit()
    db.refresh(f)
    return _enrich_friendship(f, db)


@router.put("/friends/{friendship_id}", response_model=schemas.FriendshipResponse)
def respond_to_request(
    friendship_id: int,
    status: str = Query(..., pattern="^(accepted|rejected)$"),
    x_token: Optional[str] = Header(None),
    db: Session = Depends(get_db),
):
    me = get_current_user(x_token, db)
    f = db.query(models.Friendship).filter(models.Friendship.id == friendship_id).first()
    if not f:
        raise HTTPException(status_code=404, detail="Not found")
    if f.receiver_id != me.id:
        raise HTTPException(status_code=403, detail="Only the receiver can respond")
    f.status = status
    db.commit()
    db.refresh(f)
    return _enrich_friendship(f, db)


@router.delete("/friends/{friendship_id}")
def remove_friend(
    friendship_id: int,
    x_token: Optional[str] = Header(None),
    db: Session = Depends(get_db),
):
    me = get_current_user(x_token, db)
    f = db.query(models.Friendship).filter(models.Friendship.id == friendship_id).first()
    if not f:
        raise HTTPException(status_code=404, detail="Not found")
    if f.requester_id != me.id and f.receiver_id != me.id:
        raise HTTPException(status_code=403, detail="Not authorized")
    db.delete(f)
    db.commit()
    return {"ok": True}


# ─── Challenges (authenticated — mobile app) ──────────────────────────────────

@router.get("/challenges", response_model=List[schemas.ChallengeResponse])
def list_my_challenges(
    x_token: Optional[str] = Header(None),
    db: Session = Depends(get_db),
):
    me = get_current_user(x_token, db)
    rows = db.query(models.Challenge).filter(
        (models.Challenge.challenger_id == me.id) |
        (models.Challenge.challenged_id == me.id)
    ).order_by(models.Challenge.created_at.desc()).all()
    return [_enrich_challenge(c, db) for c in rows]


@router.post("/challenges", response_model=schemas.ChallengeResponse)
def create_challenge(
    data: schemas.ChallengeCreate,
    x_token: Optional[str] = Header(None),
    db: Session = Depends(get_db),
):
    me = get_current_user(x_token, db)
    challenged = db.query(models.User).filter(models.User.username == data.challenged_username).first()
    if not challenged:
        raise HTTPException(status_code=404, detail="User not found")
    if challenged.id == me.id:
        raise HTTPException(status_code=400, detail="Cannot challenge yourself")
    try:
        start = date_type.fromisoformat(data.start_date)
        end = date_type.fromisoformat(data.end_date)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD")
    if start >= end:
        raise HTTPException(status_code=400, detail="start_date must be before end_date")
    c = models.Challenge(
        title=data.title,
        challenger_id=me.id,
        challenged_id=challenged.id,
        type=data.type,
        target=data.target,
        start_date=data.start_date,
        end_date=data.end_date,
    )
    db.add(c)
    db.commit()
    db.refresh(c)
    return _enrich_challenge(c, db)


@router.put("/challenges/{challenge_id}", response_model=schemas.ChallengeResponse)
def update_challenge(
    challenge_id: int,
    data: schemas.ChallengeUpdate,
    x_token: Optional[str] = Header(None),
    db: Session = Depends(get_db),
):
    me = get_current_user(x_token, db)
    c = db.query(models.Challenge).filter(models.Challenge.id == challenge_id).first()
    if not c:
        raise HTTPException(status_code=404, detail="Not found")
    if c.challenger_id != me.id and c.challenged_id != me.id:
        raise HTTPException(status_code=403, detail="Not authorized")
    for field, value in data.model_dump(exclude_none=True).items():
        setattr(c, field, value)
    _check_challenge_winner(c)
    db.commit()
    db.refresh(c)
    return _enrich_challenge(c, db)


# ─── Activity feed (authenticated — mobile app) ───────────────────────────────

@router.get("/activity", response_model=List[schemas.ActivityLogResponse])
def get_my_feed(
    limit: int = 50,
    x_token: Optional[str] = Header(None),
    db: Session = Depends(get_db),
):
    me = get_current_user(x_token, db)
    # Include own logs + accepted friends' public logs
    friendships = db.query(models.Friendship).filter(
        ((models.Friendship.requester_id == me.id) | (models.Friendship.receiver_id == me.id)) &
        (models.Friendship.status == "accepted")
    ).all()
    visible_ids = {me.id}
    for f in friendships:
        visible_ids.add(f.requester_id)
        visible_ids.add(f.receiver_id)
    rows = (
        db.query(models.ActivityLog)
        .filter(
            models.ActivityLog.user_id.in_(list(visible_ids)),
            models.ActivityLog.is_public == True,
        )
        .order_by(models.ActivityLog.created_at.desc())
        .limit(limit)
        .all()
    )
    return [_enrich_log(log, db) for log in rows]


@router.post("/activity", response_model=schemas.ActivityLogResponse)
def log_activity(
    data: schemas.ActivityLogCreate,
    x_token: Optional[str] = Header(None),
    db: Session = Depends(get_db),
):
    me = get_current_user(x_token, db)
    log = models.ActivityLog(
        user_id=me.id,
        type=data.type,
        description=data.description,
        data=data.data,
        is_public=data.is_public,
    )
    db.add(log)
    db.commit()
    db.refresh(log)
    return _enrich_log(log, db)


# ─── Admin endpoints (no auth — dashboard use) ───────────────────────────────

@router.get("/admin/friendships", response_model=List[schemas.FriendshipResponse])
def admin_list_friendships(db: Session = Depends(get_db)):
    rows = db.query(models.Friendship).order_by(models.Friendship.created_at.desc()).all()
    return [_enrich_friendship(f, db) for f in rows]


@router.put("/admin/friendships/{friendship_id}", response_model=schemas.FriendshipResponse)
def admin_update_friendship(
    friendship_id: int,
    status: str = Query(..., pattern="^(accepted|rejected|pending)$"),
    db: Session = Depends(get_db),
):
    f = db.query(models.Friendship).filter(models.Friendship.id == friendship_id).first()
    if not f:
        raise HTTPException(status_code=404, detail="Not found")
    f.status = status
    db.commit()
    db.refresh(f)
    return _enrich_friendship(f, db)


@router.delete("/admin/friendships/{friendship_id}")
def admin_delete_friendship(friendship_id: int, db: Session = Depends(get_db)):
    f = db.query(models.Friendship).filter(models.Friendship.id == friendship_id).first()
    if not f:
        raise HTTPException(status_code=404, detail="Not found")
    db.delete(f)
    db.commit()
    return {"ok": True}


@router.get("/admin/challenges", response_model=List[schemas.ChallengeResponse])
def admin_list_challenges(db: Session = Depends(get_db)):
    rows = db.query(models.Challenge).order_by(models.Challenge.created_at.desc()).all()
    return [_enrich_challenge(c, db) for c in rows]


@router.post("/admin/challenges", response_model=schemas.ChallengeResponse)
def admin_create_challenge(data: schemas.ChallengeCreate, db: Session = Depends(get_db)):
    challenger = db.query(models.User).filter(models.User.username == data.challenged_username).first()
    # For admin creation we swap semantics: challenged_username is the challenged party.
    # Challenger must be set differently — here we reuse the same field for simplicity.
    # Admin can create a challenge between any two users by providing both usernames
    # via the title field as "challenger_username vs challenged_username" pattern.
    # A simpler approach: the endpoint accepts challenger_id directly.
    raise HTTPException(status_code=501, detail="Use /admin/challenges/create instead")


@router.post("/admin/challenges/create", response_model=schemas.ChallengeResponse)
def admin_create_challenge_direct(
    challenger_id: int,
    challenged_id: int,
    title: str,
    type: str = "blocks",
    target: int = 10,
    start_date: str = "",
    end_date: str = "",
    db: Session = Depends(get_db),
):
    """Create a challenge between any two users directly from the dashboard."""
    challenger = db.query(models.User).get(challenger_id)
    challenged = db.query(models.User).get(challenged_id)
    if not challenger or not challenged:
        raise HTTPException(status_code=404, detail="User not found")
    c = models.Challenge(
        title=title,
        challenger_id=challenger_id,
        challenged_id=challenged_id,
        type=type,
        target=target,
        start_date=start_date,
        end_date=end_date,
        status="active",
    )
    db.add(c)
    db.commit()
    db.refresh(c)
    return _enrich_challenge(c, db)


@router.delete("/admin/challenges/{challenge_id}")
def admin_delete_challenge(challenge_id: int, db: Session = Depends(get_db)):
    c = db.query(models.Challenge).filter(models.Challenge.id == challenge_id).first()
    if not c:
        raise HTTPException(status_code=404, detail="Not found")
    db.delete(c)
    db.commit()
    return {"ok": True}


@router.get("/admin/activity", response_model=List[schemas.ActivityLogResponse])
def admin_activity_feed(limit: int = 100, db: Session = Depends(get_db)):
    rows = (
        db.query(models.ActivityLog)
        .order_by(models.ActivityLog.created_at.desc())
        .limit(limit)
        .all()
    )
    return [_enrich_log(log, db) for log in rows]


@router.delete("/admin/activity/{log_id}")
def admin_delete_activity(log_id: int, db: Session = Depends(get_db)):
    log = db.query(models.ActivityLog).filter(models.ActivityLog.id == log_id).first()
    if not log:
        raise HTTPException(status_code=404, detail="Not found")
    db.delete(log)
    db.commit()
    return {"ok": True}
