from fastapi import APIRouter, Depends

from app import db
from app.api.deps import get_current_user
from app.models import OrderIn
from app.services.billing import charge

router = APIRouter()


@router.get("/{order_id}")
def read_order(order_id: int, user_id: int = Depends(get_current_user)):
    return {"order": db.get_order(order_id), "user": user_id}


@router.post("/")
def create_order(body: OrderIn, user_id: int = Depends(get_current_user)):
    receipt = charge(user_id, body.product_id, body.quantity)
    print("order created", receipt)
    return {"receipt": receipt}
