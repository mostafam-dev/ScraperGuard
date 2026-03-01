"""Schema for the example spider."""

from scraperguard.core.schema.base import BaseSchema
from scraperguard.core.schema.validators import validators


class ProductSchema(BaseSchema):
    title: str
    price: float = validators.range(min=0.01)
    availability: bool
    rating: float = validators.range(min=0, max=5)
