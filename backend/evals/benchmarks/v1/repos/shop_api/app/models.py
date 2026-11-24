"""Persistence and API schemas."""
from pydantic import BaseModel
from sqlalchemy import Column, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class Product(Base):
    __tablename__ = "products"
    id = Column(Integer, primary_key=True)
    name = Column(String(200), nullable=False)
    price = Column(Numeric(10, 2), nullable=False)


class Order(Base):
    __tablename__ = "orders"
    id = Column(Integer, primary_key=True)
    product_id = Column(Integer, ForeignKey("products.id"))
    quantity = Column(Integer, default=1)


class ProductOut(BaseModel):
    id: int
    name: str
    price: float


class OrderIn(BaseModel):
    product_id: int
    quantity: int = 1
