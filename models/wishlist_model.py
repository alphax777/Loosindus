from enum import Enum

from config import Config

if Config.DEBUG:
    from flask_babel import gettext as _
else:
    from flask_babelex import gettext as _
from main import db

# To make sure these strings get translated
unclaimed = _("Unclaimed")
reserved = _("Reserved")
purchased = _("Purchased")
modified = _("Modified")


class NoteState(Enum):
    """
    Describes all the possible states of a wishlist item
    """
    DEFAULT = {"id": -1, "description": "Unclaimed", "color": "#4CAF50"}
    """Default state"""
    PLANNING_TO_PURCHASE = {"id": 0, "description": "Reserved", "color": "#FFEB3B"}
    """Plans to purchase"""
    PURCHASED = {"id": 2, "description": "Purchased", "color": "#F44336"}
    """Purchased"""
    MODIFIED = {"id": 3, "description": "Modified", "color": "#4CAF50"}
    """Modified"""


class Wishlist(db.Model):
    """
    Specifies how wishlist items are held in the database

    @type  user_id: int
    @param user_id: user's ID
    @type  item: str
    @param item: content of the wishlist item
    @type  status: NoteState
    @param status: status of the item
    @type  purchased_by: int
    @param purchased_by: item has been claimed by whom
    """
    __tablename__ = "wishlists"

    user_id = db.Column(db.Integer)
    item = db.Column(db.VARCHAR(255))
    status = db.Column(db.Integer)
    purchased_by = db.Column(db.Integer, nullable=True)
    id = db.Column(db.BIGINT, primary_key=True, autoincrement=True, nullable=False)

    def __init__(self, user_id, item, status=NoteState.DEFAULT.value["id"], purchased_by=None):
        self.user_id = user_id
        self.item = item
        self.status = status
        self.purchased_by = purchased_by

    def __repr__(self):
        return "<id {}>".format(self.user_id)
