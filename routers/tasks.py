from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional

from database import get_db
import models
import schemas

router = APIRouter()


@router.get("/", response_model=List[schemas.TaskResponse])
def list_tasks(
    date: Optional[str] = Query(None, description="Filter by ISO date prefix, e.g. 2026-03-25"),
    status: Optional[int] = Query(None, description="0=pending, 1=inProgress, 2=completed"),
    mode: Optional[int] = Query(None, description="0=calendar, 1=smart"),
    category_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
):
    query = db.query(models.Task)

    if date:
        query = query.filter(models.Task.date.startswith(date))
    if status is not None:
        query = query.filter(models.Task.status == status)
    if mode is not None:
        query = query.filter(models.Task.mode == mode)
    if category_id is not None:
        query = query.filter(models.Task.category_id == category_id)

    return (
        query.order_by(models.Task.date, models.Task.day_order)
        .all()
    )


@router.get("/{task_id}", response_model=schemas.TaskResponse)
def get_task(task_id: str, db: Session = Depends(get_db)):
    task = db.query(models.Task).filter(models.Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@router.post("/", response_model=schemas.TaskResponse, status_code=201)
def create_task(task: schemas.TaskCreate, db: Session = Depends(get_db)):
    existing = db.query(models.Task).filter(models.Task.id == task.id).first()
    if existing:
        raise HTTPException(status_code=400, detail="Task ID already exists")

    db_task = models.Task(**task.model_dump())
    db.add(db_task)
    db.commit()
    db.refresh(db_task)
    return db_task


@router.put("/{task_id}", response_model=schemas.TaskResponse)
def update_task(
    task_id: str,
    task: schemas.TaskUpdate,
    db: Session = Depends(get_db),
):
    db_task = db.query(models.Task).filter(models.Task.id == task_id).first()
    if not db_task:
        raise HTTPException(status_code=404, detail="Task not found")

    for field, value in task.model_dump(exclude_unset=True).items():
        setattr(db_task, field, value)

    db.commit()
    db.refresh(db_task)
    return db_task


@router.delete("/{task_id}")
def delete_task(task_id: str, db: Session = Depends(get_db)):
    db_task = db.query(models.Task).filter(models.Task.id == task_id).first()
    if not db_task:
        raise HTTPException(status_code=404, detail="Task not found")

    db.delete(db_task)
    db.commit()
    return {"message": "Task deleted"}


@router.post("/bulk", response_model=schemas.BulkSyncResult)
def bulk_sync(tasks: List[schemas.TaskCreate], db: Session = Depends(get_db)):
    """
    Upsert a list of tasks from the mobile app.
    Existing tasks (matched by ID) are updated; new ones are created.
    """
    created = 0
    updated = 0

    for task in tasks:
        existing = db.query(models.Task).filter(models.Task.id == task.id).first()
        if existing:
            for field, value in task.model_dump().items():
                setattr(existing, field, value)
            updated += 1
        else:
            db.add(models.Task(**task.model_dump()))
            created += 1

    db.commit()
    return {"created": created, "updated": updated}
