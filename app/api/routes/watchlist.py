from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from pydantic import BaseModel

from app.api.database.database import get_db
from app.models.watchlist import Watchlist

router = APIRouter(prefix="/api/watchlist", tags=["watchlist"])

class WatchItemCreate(BaseModel):
    stock_id: int
    user_id: int

class WatchItemResponse(BaseModel):
    watchlist_id: int
    stock_id: int
    user_id: int

    class Config:
        from_attributes = True

@router.get("/user/{user_id}", response_model=List[WatchItemResponse])
def get_user_watchlist(user_id: int, db: Session = Depends(get_db)):
    watchlist = db.query(Watchlist).filter(Watchlist.user_id == user_id).all()
    return watchlist

@router.post("/", response_model=WatchItemResponse)
def add_to_watchlist(watch_item: WatchItemCreate, db: Session = Depends(get_db)):
    db_watch_item = Watchlist(**watch_item.dict())
    db.add(db_watch_item)
    db.commit()
    db.refresh(db_watch_item)
    return db_watch_item

@router.delete("/{watchlist_id}")
def remove_from_watchlist(watchlist_id: int, db: Session = Depends(get_db)):
    watch_item = db.query(Watchlist).filter(Watchlist.watchlist_id == watchlist_id).first()
    if not watch_item:
        raise HTTPException(status_code=404, detail="Watch item not found")
    db.delete(watch_item)
    db.commit()
    return {"message": "Watch item removed"}
