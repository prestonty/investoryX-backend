from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from pydantic import BaseModel

from src.api.database.database import get_db
from src.api.auth.auth import get_current_active_user
from src.models.watchlist import Watchlist
from src.models.users import Users

router = APIRouter(prefix="/api/watchlist", tags=["watchlist"])

class WatchItemCreate(BaseModel):
    stock_id: int

class WatchItemResponse(BaseModel):
    watchlist_id: int
    stock_id: int
    user_id: int

    class Config:
        from_attributes = True

@router.get("/", response_model=List[WatchItemResponse])
def get_user_watchlist(
    db: Session = Depends(get_db),
    current_user: Users = Depends(get_current_active_user)
):
    """Get current user's watchlist (requires authentication)."""
    watchlist = db.query(Watchlist).filter(Watchlist.user_id == current_user.user_id).all()
    return watchlist

@router.post("/", response_model=WatchItemResponse)
def add_to_watchlist(
    watch_item: WatchItemCreate, 
    db: Session = Depends(get_db),
    current_user: Users = Depends(get_current_active_user)
):
    """Add a stock to current user's watchlist (requires authentication)."""
    # Check if item already exists in user's watchlist
    existing_item = db.query(Watchlist).filter(
        Watchlist.user_id == current_user.user_id,
        Watchlist.stock_id == watch_item.stock_id
    ).first()
    
    if existing_item:
        raise HTTPException(status_code=400, detail="Stock already in watchlist")
    
    db_watch_item = Watchlist(
        stock_id=watch_item.stock_id,
        user_id=current_user.user_id
    )
    db.add(db_watch_item)
    db.commit()
    db.refresh(db_watch_item)
    return db_watch_item

@router.delete("/{watchlist_id}")
def remove_from_watchlist(
    watchlist_id: int, 
    db: Session = Depends(get_db),
    current_user: Users = Depends(get_current_active_user)
):
    """Remove a stock from current user's watchlist (requires authentication)."""
    watch_item = db.query(Watchlist).filter(
        Watchlist.watchlist_id == watchlist_id,
        Watchlist.user_id == current_user.user_id  # Ensure user can only delete their own items
    ).first()
    
    if not watch_item:
        raise HTTPException(status_code=404, detail="Watch item not found")
    
    db.delete(watch_item)
    db.commit()
    return {"message": "Watch item removed"}
