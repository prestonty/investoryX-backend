from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Optional
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError

from src.api.database.database import get_db
from src.api.auth.auth import get_current_active_user
from src.models.watchlist import Watchlist
from src.models.users import Users
from src.models.stocks import Stocks

router = APIRouter(prefix="/api/watchlist", tags=["watchlist"])


class MessageResponse(BaseModel):
    message: str


class WatchItemCreate(BaseModel):
    stock_id: int


class WatchItemResponse(BaseModel):
    watchlist_id: int
    stock_id: int
    user_id: int

    class Config:
        from_attributes = True


def get_watch_item_by_id(
    db: Session,
    watchlist_id: int,
    user_id: int,
) -> Optional[Watchlist]:
    return (
        db.query(Watchlist)
        .filter(
            Watchlist.watchlist_id == watchlist_id,
            Watchlist.user_id == user_id,
        )
        .first()
    )


def get_watch_item_by_stock(
    db: Session,
    stock_id: int,
    user_id: int,
) -> Optional[Watchlist]:
    return (
        db.query(Watchlist)
        .filter(
            Watchlist.stock_id == stock_id,
            Watchlist.user_id == user_id,
        )
        .first()
    )


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
    # Ensure stock exists
    stock = db.query(Stocks).filter(Stocks.stock_id == watch_item.stock_id).first()
    if not stock:
        raise HTTPException(status_code=404, detail="Stock not found")

    db_watch_item = Watchlist(
        stock_id=watch_item.stock_id,
        user_id=current_user.user_id
    )
    db.add(db_watch_item)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail="Stock already in watchlist")
    db.refresh(db_watch_item)
    return db_watch_item

@router.delete("/{watchlist_id}", response_model=MessageResponse)
def remove_from_watchlist(
    watchlist_id: int, 
    db: Session = Depends(get_db),
    current_user: Users = Depends(get_current_active_user)
):
    """Remove a stock from current user's watchlist (requires authentication)."""
    watch_item = get_watch_item_by_id(db, watchlist_id, current_user.user_id)
    
    if not watch_item:
        raise HTTPException(status_code=404, detail="Watch item not found")
    
    db.delete(watch_item)
    db.commit()
    return {"message": "Watch item removed"}

@router.delete("/by-stock/{stock_id}", response_model=MessageResponse)
def remove_from_watchlist_by_stock(
    stock_id: int,
    db: Session = Depends(get_db),
    current_user: Users = Depends(get_current_active_user)
):
    """Remove a stock from current user's watchlist by stock_id."""
    watch_item = get_watch_item_by_stock(db, stock_id, current_user.user_id)

    if not watch_item:
        raise HTTPException(status_code=404, detail="Watch item not found")

    db.delete(watch_item)
    db.commit()
    return {"message": "Watch item removed"}
