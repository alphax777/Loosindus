# coding=utf-8
# Copyright: Taavi Eomäe 2017-2020
# SPDX-License-Identifier: AGPL-3.0-only
"""
Contains everything very directly related to users
"""
from __future__ import annotations

from datetime import datetime
from typing import List

import sentry_sdk
from flask_dance.consumer.storage.sqla import OAuthConsumerMixin
from flask_security import RoleMixin, UserMixin
from sqlalchemy import Boolean, Column, DateTime, FetchedValue, ForeignKey, Integer, VARCHAR, and_
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import backref, relationship

from main import db
from models.audit_events_model import AuditEvent
from models.enums import audit_event_type_to_id


class Role(db.Model, RoleMixin):
    """
    Described how roles are assigned to users
    """
    __tablename__ = "roles"
    id: int = Column(Integer(), server_default=FetchedValue(), primary_key=True, unique=True, nullable=False)
    name: str = Column(VARCHAR(80), unique=True)
    description: str = Column(VARCHAR(255))

    def __str__(self):
        return self.name

    def __hash__(self):
        return hash(self.name)


class User(db.Model, UserMixin):
    __tablename__ = "users"
    id: int = Column(Integer, server_default=FetchedValue(), primary_key=True, unique=True, nullable=False)
    email: str = Column(VARCHAR(255), unique=True)
    first_name: str = Column(VARCHAR(255), nullable=False)
    password: str = Column(VARCHAR(255), nullable=False)
    confirmed_at: datetime = Column(DateTime())
    active: bool = Column(Boolean())

    birthday: datetime = Column(DateTime())
    language: str = Column(VARCHAR(5), default="en", nullable=False)
    uuid: str = Column(UUID, nullable=False, server_default=FetchedValue(), unique=True)

    roles: List[Role] = relationship(
        Role,
        secondary="roles_users",
        backref=backref("User", lazy="dynamic")
    )

    families: List[Family] = relationship(
        "Family",
        secondary="users_families",
        backref=backref("User", lazy="dynamic")
    )

    @property
    def last_login_ip(self):
        try:
            return AuditEvent.query.filter(and_(AuditEvent.type_id == audit_event_type_to_id["last_login"],
                                                AuditEvent.user_id == self.id)).order_by("when").limit(1).one().ip
        except Exception:
            return ""

    @last_login_ip.setter
    def last_login_ip(self, value):
        AuditEvent(audit_event_type_to_id["last_login"], self.id, value)
        self.last_login_ip = value

    @property
    def last_login_at(self):
        try:
            return AuditEvent.query.filter(and_(AuditEvent.type_id == audit_event_type_to_id["last_login"],
                                                AuditEvent.user_id == self.id)).order_by("when").limit(1).one().when
        except Exception as e:
            sentry_sdk.capture_exception(e)
            return ""

    @last_login_at.setter
    def last_login_at(self, value):
        # This is already set when last_login_ip is set
        return None

    @property
    def current_login_at(self):
        # TODO:
        return

    @current_login_at.setter
    def current_login_at(self, value):
        # TODO:
        self.current_login_at = value

    @property
    def current_login_ip(self):
        # TODO:
        return

    @current_login_ip.setter
    def current_login_ip(self, value):
        # TODO:
        self.current_login_ip = value

    def __init__(self, email, username, password, active=False):
        self.email = email
        self.username = username
        self.password = password
        self.active = active


class RolesUsers(db.Model):
    """
    Specifies what role an User has
    """
    __tablename__ = "roles_users"
    id = Column(Integer(), ForeignKey(User.id), primary_key=True)
    role_id = Column(Integer(), ForeignKey(Role.id))


class AuthLinks(db.Model, OAuthConsumerMixin):
    """
    Specifies how 3rd party identity providers are linked to users
    """
    __tablename__ = "users_connections"
    id = Column(Integer, server_default=FetchedValue(), primary_key=True, unique=True, nullable=False)
    user_id = Column(Integer, ForeignKey(User.id), nullable=False)
    provider_user_id = Column(VARCHAR(255), nullable=False)
    created_at = Column(DateTime, default=datetime.now(), nullable=False)
    token = Column(VARCHAR(255), nullable=True)
    provider = Column(VARCHAR(255), nullable=False)

    def __init__(self, provider, provider_user_id, token):
        self.provider = provider
        self.provider_user_id = provider_user_id
        self.token = token

    def __init__(self, user_id, provider, provider_user_id, token):
        self.user_id = user_id
        self.provider = provider
        self.provider_user_id = provider_user_id
        self.token = token


class Email(db.Model):
    """
    Specifies how emails are stored for history and management purposes
    Users table is updated based on this table by a stored procedure
    """
    __tablename__ = "emails"

    user_id: int = Column(Integer, ForeignKey(User.id), nullable=False)
    email: str = Column(VARCHAR(255), primary_key=True, unique=True, nullable=False)
    verified: bool = Column(Boolean, default=False, nullable=False)
    primary: bool = Column(Boolean, default=False, nullable=False)
    added: datetime = Column(DateTime, server_default=FetchedValue(), nullable=False)


class Password(db.Model):
    """
    Specifies how passwords are stored in the database,
    Users table is updated based on this table by a stored procedure
    """
    __tablename__ = "passwords"

    password: str = Column(VARCHAR(255), primary_key=True, unique=True, nullable=False)
    user_id: int = Column(Integer, ForeignKey(User.id), nullable=False)
    active: bool = Column(Boolean, default=False, nullable=False)
    created: datetime = Column(DateTime, default=datetime.now(), nullable=False)


class UserFamily(db.Model):
    """
    Specifies how users belong to families
    """
    __tablename__ = "users_families"
    user_id: int = Column(Integer, ForeignKey(User.id), primary_key=True, unique=True, nullable=False)
    family_id: int = Column(Integer, ForeignKey("families.id"), primary_key=True, nullable=False)
    confirmed: bool = Column(Boolean, nullable=False, default=False)

    def __repr__(self):
        return "<user_id {}, family_id {}>".format(self.user_id, self.group_id)
