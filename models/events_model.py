# coding=utf-8
"""
Contains all the models related to events organized in one specific group
"""

from datetime import datetime

from sqlalchemy import BigInteger, Column, FetchedValue, ForeignKey, Integer, TIMESTAMP, VARCHAR

from main import db
from models.family_model import Group


class ShufflingEventType(db.Model):
    """
    Specifies how event types are stored in the database
    """

    __tablename__ = "event_types"

    id: int = Column(BigInteger(), server_default=FetchedValue(), primary_key=True, unique=True, nullable=False)
    name: str = Column(VARCHAR(), nullable=True)


event_type_to_id: dict = {}
for event_type in ShufflingEventType.query.all():
    event_type_to_id[event_type.name.lower().replace(" ", "_")] = event_type.id


class ShufflingEvent(db.Model):
    """
    Specifies how events are stored in the database
    """

    __tablename__ = "events"

    id: int = Column(BigInteger(), server_default=FetchedValue(), primary_key=True, unique=True, nullable=False)
    created_at: datetime = Column(TIMESTAMP(), server_default=FetchedValue(), nullable=False)
    name: str = Column(VARCHAR(255), nullable=False)
    event_at: datetime = Column(TIMESTAMP(), nullable=True)
    group_id: int = Column(Integer(), ForeignKey(Group.id), nullable=False)
    event_type: int = Column(Integer(), ForeignKey(ShufflingEventType.id), nullable=False)

    def __str__(self):
        return "{" \
               "\"id\": {id}, " \
               "\"created_at\": \"{created_at}\", " \
               "\"name\": \"{name}\", " \
               "\"event_at\": \"{event_at}\", " \
               "\"group_id\": {group_id}, " \
               "\"event_type\": {event_type}" \
               "}".format(
            id=self.id,
            created_at=self.created_at,
            name=self.name,
            event_at=self.year,
            group_id=self.group,
            event_type=self.event_type
        )

    def as_dict(self):
        return {
            "id": self.id,
            "created_at": self.created_at,
            "name": self.name,
            "event_at": self.event_at,
            "group_id": self.group_id,
            "event_type": self.event_type,
        }

    def __hash__(self):
        return hash(str(self))