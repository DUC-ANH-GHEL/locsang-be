from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from app.core.database import Base

class ProductImage(Base):
    __tablename__ = "product_images"

    id = Column(Integer, primary_key=True, index=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    url = Column(String, nullable=False)
    type = Column(String, nullable=False, default="image")
    public_id = Column(String, nullable=True)
    alt_text = Column(String, nullable=True)
    sort_order = Column(Integer, nullable=False, default=0)
    is_primary = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    product = relationship("Product", back_populates="images")

class Product(Base):
    __tablename__ = "products"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    slug = Column(String, nullable=False, unique=True)
    short_description = Column(Text, nullable=True)
    description = Column(Text, nullable=True)

    # Admin status fields
    status = Column(String, nullable=False, default="active")
    featured = Column(Boolean, nullable=False, default=False)
    tags = Column(JSONB, nullable=True)
    specifications = Column(JSONB, nullable=True)
    has_variants = Column(Boolean, nullable=False, default=True)
    deleted_at = Column(DateTime, nullable=True)

    price = Column(Float, nullable=False)
    sale_price = Column(Float, nullable=True)
    thumbnail = Column(String, nullable=True)
    currency = Column(String, nullable=False, default="VND")
    sku = Column(String, unique=True, index=True)
    is_active = Column(Boolean, default=True)
    stock = Column(Integer, nullable=False, default=0)

    brand = Column(String, nullable=True)
    category_id = Column(Integer)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    order_items = relationship("OrderItem", back_populates="product")
    images = relationship(
        "ProductImage",
        back_populates="product",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    variants = relationship(
        "ProductVariant",
        back_populates="product",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    attributes = relationship(
        "ProductAttribute",
        back_populates="product",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class ProductVariant(Base):
    __tablename__ = "product_variants"

    id = Column(Integer, primary_key=True, index=True)
    product_id = Column(Integer, ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True)

    sku = Column(String, nullable=False, unique=True, index=True)

    price = Column(Float, nullable=True)
    sale_price = Column(Float, nullable=True)
    stock = Column(Integer, nullable=False, default=0)
    manage_stock = Column(Boolean, nullable=False, default=True)
    allow_backorder = Column(Boolean, nullable=False, default=False)
    status = Column(String, nullable=False, default="active")
    is_active = Column(Boolean, nullable=False, default=True)

    image_url = Column(String, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    product = relationship("Product", back_populates="variants")

    attribute_values = relationship(
        "VariantAttributeValue",
        back_populates="variant",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class ProductAttribute(Base):
    __tablename__ = "product_attributes"

    id = Column(Integer, primary_key=True, index=True)
    product_id = Column(Integer, ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint("product_id", "name", name="uq_product_attributes_product_name"),
    )

    product = relationship("Product", back_populates="attributes")
    values = relationship(
        "ProductAttributeValue",
        back_populates="attribute",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class ProductAttributeValue(Base):
    __tablename__ = "product_attribute_values"

    id = Column(Integer, primary_key=True, index=True)
    attribute_id = Column(Integer, ForeignKey("product_attributes.id", ondelete="CASCADE"), nullable=False, index=True)
    value = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint("attribute_id", "value", name="uq_product_attribute_values_attribute_value"),
    )

    attribute = relationship("ProductAttribute", back_populates="values")


class VariantAttributeValue(Base):
    __tablename__ = "variant_attribute_values"

    id = Column(Integer, primary_key=True, index=True)
    variant_id = Column(Integer, ForeignKey("product_variants.id", ondelete="CASCADE"), nullable=False, index=True)
    attribute_id = Column(Integer, ForeignKey("product_attributes.id", ondelete="CASCADE"), nullable=False, index=True)
    attribute_value_id = Column(Integer, ForeignKey("product_attribute_values.id", ondelete="CASCADE"), nullable=False, index=True)

    __table_args__ = (
        UniqueConstraint("variant_id", "attribute_id", name="uq_variant_attribute_values_variant_attribute"),
    )

    variant = relationship("ProductVariant", back_populates="attribute_values")
    attribute = relationship("ProductAttribute")
    attribute_value = relationship("ProductAttributeValue")
