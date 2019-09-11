# coding=utf-8
# Copyright: Taavi Eomäe 2017-2019
# SPDX-License-Identifier: AGPL-3.0-only
"""
A simple Secret Santa website in Python
Copyright © 2017-2019 Taavi Eomäe

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU Affero General Public License as published by
the Free Software Foundation, version 3 of the License.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU Affero General Public License for more details.

You should have received a copy of the GNU Affero General Public License
along with this program.  If not, see <https://www.gnu.org/licenses/>.
"""
# Cython
from json import dumps
from typing import List

import pyximport

from models.events_model import ShufflingEvent
from models.family_model import Group
from models.wishlist_model import Wishlist, wishlist_status_to_id

pyximport.install()

# Utilities
from logging import getLogger
from secrets import token_bytes

# Graphing
import secretsanta

# App specific config
from config import Config

getLogger().setLevel(Config.LOGLEVEL)
logger = getLogger()

# Flask
from flask import request, render_template, redirect, Blueprint, flash, url_for
from flask_security import login_required
from flask_security.utils import verify_password, hash_password
from flask_login import current_user, login_user
from flask_mail import Message
from flask_dance.consumer import oauth_authorized
from flask_dance.consumer.storage.sqla import SQLAlchemyStorage
from flask_dance.contrib.facebook import make_facebook_blueprint
from flask_dance.contrib.github import make_github_blueprint
from flask_dance.contrib.google import make_google_blueprint
from flask_babelex import Domain, gettext as _

# from sqlalchemy import and_
from sqlalchemy.orm.exc import NoResultFound
from main import babel

domain = Domain(domain="messages")


@babel.localeselector
def get_locale():
    """
    Deals with displaying the correct localization with possible override
    :return: user locale
    """
    if current_user.is_authenticated:
        user_id = session["user_id"]
    else:
        return request.accept_languages.best_match(["et", "en"])

    try:
        language_code = get_person_language_code(user_id)
    except Exception:
        return request.accept_languages.best_match(["et", "en"])

    if language_code is None:
        return request.accept_languages.best_match(["et", "en"])
    else:
        return language_code


# Database models
from main import db
from models.users_model import AuthLinks

main_page = Blueprint("main_page", __name__, template_folder="templates")

from main import app
# from main import sentry
from utility import *
from utility_standalone import *

set_recursionlimit()

# Just for assigning members_to_families a few colors
chistmasy_colors = ["#E5282A", "#DC3D2A", "#0DEF42", "#00B32C", "#0D5901"]

# Mailing
from main import security


def index():
    """
    Displays the main overview page
    """
    Domain(domain="messages")

    try:
        security.datastore.commit()
    except Exception:
        pass

    user_id = get_user_id()
    user = get_person(user_id)

    user_events: List[dict] = []
    for user_family in user.families:
        for family_group in user_family.groups:
            for group_event in family_group.events:
                if datetime.now() < group_event.event_at:  # If event has taken place
                    group_event.group_name = family_group.name
                    user_events.append(group_event)


    try:
        # user.last_activity_at = datetime.datetime.now()
        # user.last_activity_ip = request.headers.getlist("X-Forwarded-For")[0].rpartition(" ")[-1]
        # db.session.commit()
        pass
    except Exception as e:
        sentry_sdk.capture_exception(e)

    return render_template("index.html",
                           auth=user.first_name,
                           events=user_events,
                           uid=user_id,
                           title=_("Home"))


@main_page.route("/shuffles")
@login_required
def shuffles():
    """
    Returns all the graphs the user could view
    """
    user_id = get_user_id()
    all_shuffles = list(Shuffle.query.filter(Shuffle.giver == user_id).all())
    shuffles = []
    for shuffle in all_shuffles:
        event = ShufflingEvent.query.get(shuffle.event_id)
        shuffle.event_name = event.name
        shuffle.group_id = event.group_id
        shuffle.group_name = Group.query.get(event.group_id).name
        shuffle.giver_name = User.query.get(shuffle.giver).first_name
        shuffle.getter_name = User.query.get(shuffle.getter).first_name
        if datetime.now() > event.event_at:
            shuffles.append(shuffle)

    return render_template("table_views/shuffles.html",
                           title=_("Shuffles"),
                           shuffles=shuffles)


@main_page.route("/shuffle/<event_id>")
@login_required
def shuffle(event_id: str):
    """
    Returns a page that displays a specific event's shuffle
    """
    user_id = get_user_id()
    user = User.query.get(user_id)
    username = user.first_name
    event_id = int(event_id)

    shuffle = Shuffle.query.get((user_id, event_id))

    logger.debug("Username: {}, From: {}, To: {}", username, shuffle.giver, shuffle.getter)
    return render_template("shuffle.html",
                           title=_("Shuffle"),
                           id=user_id)


@main_page.route("/event/<event_id>")
@login_required
def event(event_id: str):
    """
    Displays all the families in the event
    """
    user_id = get_user_id()
    event_id = int(event_id)
    event = ShufflingEvent.query.get(event_id)
    if not event:
        return render_template("utility/error.html")

    group = Group.query.get(event.group_id)

    authorized = False
    for family in group.families:
        for member in family.members:
            if member.id == user_id:
                authorized = True
                break

    if not authorized:
        return render_template("utility/error.html")

    return render_template("table_views/families.html",
                           families=group.families,
                           group_id=group.id,
                           title=_("Event"))


@main_page.route("/family/<group_id>/<family_id>")
@main_page.route("/family/<family_id>")
@login_required
def family(family_id: str, group_id: str = None):
    """
    Displays all the people in the family
    """
    user_id = int(session["user_id"])
    family_id = int(family_id)
    family = Family.query.get(family_id)
    if not family:
        return render_template("utility/error.html",
                               message=_("You do are not authorized to access this family"))

    authorized = False
    if not group_id:
        for member in family.members:
            if member.id == user_id:
                authorized = True
                break
    else:
        authorized = True

    if not authorized:
        return render_template("utility/error.html",
                               message=_("You do are not authorized to access this family"))

    if group_id:
        group_id = int(group_id)
        group = Group.query.get(group_id)
        if not group:
            return render_template("utility/error.html",
                                   message=_("You do are not authorized to access this family"))

        authorized = False
        for member in family.members:
            if member.id == user_id:
                authorized = True
                break

        if not authorized:
            for family in group.families:
                for member in family.members:
                    if member.id == user_id:
                        authorized = True
                        break

        if not authorized:
            for group in family.groups:
                for family in group.families:
                    for member in family.members:
                        if member.id == user_id:
                            authorized = True
                            break

        if not authorized:
            return render_template("utility/error.html",
                                   message=_("You do are not authorized to access this family"))

    return render_template("table_views/users.html",
                           members=family.members,
                           family_id=family_id,
                           group_id=group_id,
                           title=_("Family"))


@main_page.route("/events")
@login_required
def events():
    """
    Displays all the events of a person
    """
    user_id = int(session["user_id"])
    user: User = User.query.get(user_id)

    events: List[ShufflingEvent] = []
    for family in user.families:
        for group in family.groups:
            for event in group.events:
                events.append(event)

    return render_template("table_views/events.html",
                           events=events)


@main_page.route("/families")
@login_required
def families():
    """
    Displays all the events of a person
    """

    user_id = int(session["user_id"])
    user = User.query.get(user_id)

    return render_template("table_views/families.html",
                           families=user.families)


@main_page.route("/groups")
@login_required
def groups():
    """
    Displays all the groups of a person
    """

    user_id = int(session["user_id"])
    user = User.query.get(user_id)

    groups = []
    for family in user.families:
        for group in family.groups:
            groups.append(group)

    return render_template("table_views/groups.html",
                           groups=groups)


@main_page.route("/notes")
@login_required
def notes():
    """
    Displays all the notes in one's wishlist
    """
    user_id = session["user_id"]
    # username = get_person_name(user_id)
    notes_from_file = {}
    empty = False

    try:
        # noinspection PyComparisonWithNone
        # SQLAlchemy doesn't like "is None"
        db_notes = Wishlist.query.filter(Wishlist.user_id == user_id).all()
        for note in db_notes:
            notes_from_file[note.item] = note.id
    except Exception as e:
        sentry_sdk.capture_exception(e)
        raise e

    if len(notes_from_file) <= 0:
        notes_from_file = {_("Right now there's nothing in the Wishlist"): ("", "")}
        empty = True

    return render_template("table_views/notes_private.html",
                           list=notes_from_file,
                           empty=empty,
                           title=_("My Wishlist"))


@main_page.route("/createnote", methods=["GET"])
@login_required
def createnote():
    """
    :return: Displays the form required to add a note
    """
    return render_template("creatething.html",
                           action="ADD",
                           confirm=False,
                           endpoint="createnote",
                           row_count=3,
                           label=_("Your wish"),
                           placeholder="")


@main_page.route("/createnote", methods=["POST"])
@login_required
def createnote_add():
    """
    Allows submitting new notes to a wishlist
    """
    logger.debug("Got a post request to add a note")
    user_id = int(session["user_id"])
    user: User = User.query.get(user_id)
    username = user.first_name
    logger.debug("Found user: {username} with id: {id}".format(username=username, id=user_id))
    currentnotes = {}
    addednote = request.form["textfield"]

    if len(addednote) > 1024:
        return render_template("utility/error.html",
                               message=_("You're wishing for too much"),
                               title=_("Error"))
    elif len(addednote) <= 0:
        return render_template("utility/error.html",
                               message=_("Santa can't bring you nothing, ") + username + "!",
                               title=_("Error"))

    logger.info("Trying to add a note: {}".format(addednote))
    try:
        logger.info("Opening file: {}".format(user_id))
        #    with open("./notes/" + useridno, "r") as file:
        #        currentnotes = json.load(file)
        db_notes = Wishlist.query.filter(Wishlist.user_id == user_id).all()
        for note in db_notes:
            currentnotes[note.item] = note.id
    except Exception as e:
        sentry_sdk.capture_exception(e)
        raise e

    if len(currentnotes) >= 200:
        return render_template("utility/error.html",
                               message=_("You're wishing for too much, ") + username + ".",
                               title=_("Error"))

    db_entry_notes = Wishlist(
        user_id=user_id,
        item=addednote
    )

    try:
        db.session.add(db_entry_notes)
        db.session.commit()
    except Exception as e:
        sentry_sdk.capture_exception(e)
        raise e

    return render_template("utility/success.html",
                           action=_("Added"),
                           link="./notes",
                           title=_("Added"))


@main_page.route("/editnote", methods=["GET"])
@login_required
def editnote():
    """
    Displays a page where a person can edit a note
    """
    user_id = int(session["user_id"])
    user: User = User.query.get(user_id)
    username = user.first_name

    try:
        request_id = request.args["id"]
        request_id = int(request_id)
        logger.info("{} is trying to remove a note {}".format(user_id, request_id))
    except Exception as e:
        sentry_sdk.capture_exception(e)
        return render_template("utility/error.html",
                               message=_("Pls no hax ") + username + "!!",
                               title=_("Error"))

    try:
        logger.info("{} is editing notes of {}".format(user_id, request_id))
        db_note = Wishlist.query.get(request_id)
    except Exception as e:
        sentry_sdk.capture_exception(e)
        return render_template("utility/error.html",
                               message=_("An error occured"),
                               title=_("Error"))

    return render_template("creatething.html",
                           action="ADD",
                           confirm=False,
                           endpoint="editnote",
                           row_count=3,
                           extra_data=request.args["id"],
                           label=_("Your wish"),
                           placeholder=db_note.item)


@main_page.route("/editnote", methods=["POST"])
@login_required
def editnote_edit():
    """
    Allows submitting textual edits to notes
    """
    user_id = session["user_id"]
    logger.debug("Got a post request to edit a note by user id: {}".format(user_id))

    addednote = request.form["textfield"]
    try:
        request_id = request.form["extra_data"]
        request_id = int(request_id)
    except Exception as e:
        logger.error("Error when decrypting note edit submission")
        sentry_sdk.capture_exception(e)
        return render_template("utility/error.html",
                               message=_("An error occured"),
                               title=_("Error"))

    db_note = Wishlist.query.get(request_id)

    try:
        db_note.item = addednote
        db_note.status = wishlist_status_to_id["modified"]
        db.session.commit()
    except Exception as e:
        logger.error("Error when committing note edit change into database")
        sentry_sdk.capture_exception(e)
        db.session.rollback()
        return render_template("utility/error.html",
                               message=_("An error occured"),
                               title=_("Error"))

    return render_template("utility/success.html",
                           action=_("Changed"),
                           link="./notes",
                           title=_("Changed"))


@main_page.route("/removenote", methods=["POST"])
@login_required
def deletenote():
    """
    Allows deleting a specific note
    """
    user_id = int(session["user_id"])
    user = User.query.get(user_id)
    username = user.first_name

    if "confirm" not in request.form.keys():
        return render_template("creatething.html",
                               action="DELETE",
                               endpoint="removenote",
                               extra_data=request.form["extra_data"],
                               confirm=True)

    try:
        request_id = request.form["extra_data"]
        request_id = int(request_id)
        logger.info("{} is trying to remove a note {}".format(user_id, request_id))
    except Exception as e:
        sentry_sdk.capture_exception(e)
        return render_template("utility/error.html",
                               message=_("Broken link"),
                               title=_("Error"))

    try:  # Let's try to delete it now
        Wishlist.query.filter_by(id=request_id).delete()
        db.session.commit()
    except Exception as e:
        sentry_sdk.capture_exception(e)
        return render_template("utility/error.html",
                               message=_("Can't find what you wanted to delete"),
                               title=_("Error"))

    logger.info("Removed {} note with ID {}".format(username, request_id))
    return render_template("utility/success.html",
                           action=_("Removed"),
                           link="./notes",
                           title=_("Removed"))


@main_page.route("/note/<id>", methods=["POST"])
@login_required
def update_note_status(id: str):
    """
    Allows setting specific wishlist note's status
    """
    user_id = int(session["user_id"])

    # TODO: Check if they should be able to change
    try:
        requested_status = int(request.form["status"])
        note = Wishlist.query.get(id)

        if requested_status != wishlist_status_to_id["default"]:
            # If the requested state is not default
            # If it's already been purchased or someone tries to set it to modified
            # then abort (modified only happens after edit of a note)
            if note.status == wishlist_status_to_id["purchased"] or \
                    requested_status == wishlist_status_to_id["modified"]:
                raise Exception("Invalid access")
            note.status = requested_status
            note.purchased_by = user_id
            db.session.commit()
        elif requested_status == wishlist_status_to_id["default"]:
            # If the request is to set it to default
            # If the note has already been purchased or someone tried to set it to modified
            # then abort (modified only happens after edit of a note
            if note.status == wishlist_status_to_id["purchased"] or \
                    requested_status == wishlist_status_to_id["modified"]:
                raise Exception("Invalid access")
            note.status = requested_status
            note.purchased_by = None
            db.session.commit()
        else:
            raise Exception("Invalid status code")
    except Exception as e:
        sentry_sdk.capture_exception(e)
        logger.info("Failed toggling: {}".format(e))
        return render_template("utility/error.html",
                               message=_("Could not edit"),
                               title=_("Error"),
                               back=True)

    return redirect("//" + str(id), code=303)


@main_page.route("/wishlist/<group_id>/<person_id>")
@main_page.route("/wishlist/<person_id>")
@login_required
def wishlist(person_id: str, group_id: str = None):
    """
    Display specific user's wishlist
    """
    user_id = int(session["user_id"])
    user = User.query.get(user_id)
    invalid_notes = False

    if not person_id.isnumeric():
        return render_template("utility/error.html",
                               no_sidebar=False,
                               message=_("Access denied"),
                               title=_("Access denied"))

    person_id = int(person_id)
    if person_id == user_id:
        return render_template("utility/error.html",
                               no_sidebar=False,
                               message=_("To view your own list use the sidebar"),
                               title=_("Access denied"))

    target_user = User.query.get(person_id)
    first_name = target_user.first_name

    if group_id:  # If group is given let's check if the person may access trough group
        if not group_id.isnumeric():
            return render_template("utility/error.html",
                                   no_sidebar=False,
                                   message=_("Access denied"),
                                   title=_("Access denied"))

        group_id = int(group_id)
        group = Group.query.get(group_id)
        if not group:
            return render_template("utility/error.html",
                                   no_sidebar=False,
                                   message=_("To view your own list use the sidebar"),
                                   title=_("Access denied"))

        authorized = False
        for user_family in group.families:
            for member in user_family.members:
                if member.id == user.id:
                    authorized = True
                    break

        if not authorized:
            return render_template("utility/error.html",
                                   no_sidebar=False,
                                   message=_("Not authorized"),
                                   title=_("Access denied"))
    else:  # Group wasn't given, if the person isn't in the family then forbidden
        authorized = False
        for user_family in user.families:
            for member in user_family.members:
                if member.id == user_id:
                    authorized = True
                    break

        if not authorized:
            return render_template("utility/error.html",
                                   no_sidebar=False,
                                   message=_("Not authorized"),
                                   title=_("Access denied"))


    currentnotes = []
    try:
        logger.info("{} is opening wishlist of {}".format(user_id, target_user.id))
        # noinspection PyComparisonWithNone
        db_notes: List[Wishlist] = Wishlist.query.filter(Wishlist.user_id == target_user.id).all()
        if len(db_notes) <= 0:
            raise Exception("Not a single wishlist item")

        for note in db_notes:
            all_states = list(wishlist_status_to_id.items())
            all_states.remove(("modified", wishlist_status_to_id["modified"]))
            selections = []
            modifyable = False
            name = ""

            if note.status == wishlist_status_to_id["default"] or note.status is None:
                selections = all_states
                selections.remove(("default", wishlist_status_to_id["default"]))
                selections.insert(0, ("default", wishlist_status_to_id["default"]))
                modifyable = True
            elif note.status == wishlist_status_to_id["modified"]:
                if note.purchased_by == user_id or note.purchased_by is None:
                    selections = all_states
                    selections.insert(0, ("modified", wishlist_status_to_id["modified"]))
                    modifyable = True
                else:
                    selections = [("modified", wishlist_status_to_id["modified"])]
                    modifyable = False
                name = get_christmasy_emoji(note.purchased_by)
            elif note.status == wishlist_status_to_id["purchased"]:
                selections = [("purchased", wishlist_status_to_id["purchased"])]
                name = get_christmasy_emoji(note.purchased_by)
                modifyable = False
            elif note.status == wishlist_status_to_id["booked"]:
                selections = [("booked", wishlist_status_to_id["booked"]),
                              ("default", wishlist_status_to_id["default"]),
                              ("purchased", wishlist_status_to_id["purchased"])]
                name = get_christmasy_emoji(note.purchased_by)
                if note.purchased_by == user_id:
                    modifyable = True
                else:
                    modifyable = False

            note.buyer = name
            note.statuses = selections
            note.status_modifyable = modifyable
            currentnotes.append(note)
    except ValueError as e:
        sentry_sdk.capture_exception(e)
    except Exception as e:
        currentnotes = [{}]
        invalid_notes = True
        logger.info("Error displaying notes, there might be none: {}".format(e))

    return render_template("table_views/notes_public.html",
                           notes=currentnotes,
                           target=get_name_in_genitive(first_name),
                           id=group_id,
                           title=_("Wishlist"),
                           invalid=invalid_notes,
                           back=True)


@main_page.route("/graph")
@login_required
def graph():
    """
    Display default group's graph
    """
    user_id = get_user_id()
    try:
        if "group_id" in request.args.keys():
            family_group = request.args["group_id"]
        else:
            family = get_default_family(user_id)
            family_group = FamilyGroup.query.filter(and_(FamilyGroup.family_id == family.id,
                                                         FamilyGroup.confirmed == True)
                                                    ).one().group_id

        if "unhide" in request.args.keys():  # TODO: Make prettier
            if request.args["unhide"] in "True":
                unhide = "True"
                user_number = _("or with your own name")
            else:
                unhide = ""
                user_number = get_christmasy_emoji(user_id)
        else:
            unhide = ""
            user_number = get_christmasy_emoji(user_id)
        return render_template("graph.html",
                               id=user_number,
                               graph_id=family_group,
                               unhide=unhide,
                               title=_("Graph"))
    except Exception as e:
        sentry_sdk.capture_exception(e)
        return render_template("utility/error.html",
                               message=_(
                                   "Shuffling has not yet been done for your group (or some other error occured)!"),
                               title=_("Error"),
                               no_video=True)


@main_page.route("/graph/<event_id>/<unhide>")
@main_page.route("/graph/<event_id>", defaults={"unhide": False})
@main_page.route("/graph/<event_id>/", defaults={"unhide": False})
@login_required
def graph_json(event_id, unhide):
    """
    Displays an interactive graph
    """
    user_id = int(session["user_id"])

    try:
        group_id = int(event_id)
        if unhide is "True":
            user_group_admin = UserGroupAdmin.query.filter(and_(UserGroupAdmin.user_id == user_id,
                                                                UserGroupAdmin.group_id == int(group_id),
                                                                UserGroupAdmin.confirmed == True)
                                                           ).one()
            if user_group_admin is not None and user_group_admin.admin:
                unhide = True
            else:
                unhide = False

        belongs_in_group = False
        people = {"nodes": [], "links": []}
        current_year = datetime.datetime.now().year
        database_families = get_families_in_group(group_id)

        for family in database_families:
            for user in UserFamilyAdmin.query.filter(and_(UserFamilyAdmin.family_id == family.id,
                                                          UserFamilyAdmin.confirmed == True)).all():
                if unhide:
                    people["nodes"].append({"id": get_person_name(user.user_id),
                                            "group": family.id})
                else:
                    if user.user_id == user_id:
                        belongs_in_group = True
                        people["nodes"].append({"id": get_christmasy_emoji(user.user_id),
                                                "group": 2})
                    else:
                        people["nodes"].append({"id": get_christmasy_emoji(user.user_id),
                                                "group": 1})

                shuffles = Shuffle.query.filter(and_(Shuffle.giver == user.user_id, Shuffle.year == current_year)).all()
                for shuffle_element in shuffles:
                    if unhide:
                        people["links"].append({"source": get_person_name(shuffle_element.giver),
                                                "target": get_person_name(shuffle_element.getter),
                                                "value": 0})
                    else:
                        people["links"].append(
                            {"source": get_christmasy_emoji(shuffle_element.giver),
                             "target": get_christmasy_emoji(shuffle_element.getter),
                             "value": 0})

        if belongs_in_group or unhide:
            return dumps(people), 200, {"content-type": "application/json"}
        else:
            return "{}", 200, {"content-type": "application/json"}
    except Exception as e:
        sentry_sdk.capture_exception(e)
        return "{}", 200, {"content-type": "application/json"}


@main_page.route("/grapher/<graph_id>/<unhide>")
@main_page.route("/grapher/<graph_id>", defaults={"unhide": ""})
@main_page.route("/grapher/<graph_id>/", defaults={"unhide": ""})
@login_required
def graph_js(graph_id, unhide):
    """
    Returns the JS required to graph one specific graph
    """
    return render_template("grapher.js", graph_id=graph_id, unhide=unhide), \
           200, {"content-type": "application/javascript"}


@main_page.route("/settings")
@login_required
def settings():
    """
    Displays a settings page
    """
    user_id: int = int(session["user_id"])
    user: User = User.query.get(user_id)

    if len(user.families) > 0:
        is_in_family = True
    else:
        is_in_family = False

    user_families = {}
    family_admin = False
    for family in user.families:
        family_relationship = UserFamilyAdmin.query.get((user.id, family.id))
        user_families[family.name] = (family.id, family_relationship.admin)
        if family_relationship.admin:
            family_admin = True

    user_groups = {}
    is_in_group = False
    group_admin = False
    for family in user.families:
        for group_relationship in family.groups:
            group_admin = UserGroupAdmin.query.filter(and_(
                UserGroupAdmin.user_id == user_id,
                UserGroupAdmin.group_id == group_relationship.id)).first()

            if not group_admin:
                user_groups[group_relationship.description] = (group_relationship.id, False)
            else:
                user_groups[group_relationship.description] = (group_relationship.id, group_admin.admin)
                group_admin = True

            is_in_group = True

    id_link_exists = False
    google_link_exists = False
    github_link_exists = False  # TODO: Store them all in a dictionary and render based on that
    facebook_link_exists = False
    try:
        user_links = AuthLinks.query.filter(AuthLinks.user_id == int(user_id)).all()
        for link in user_links:
            if "esteid" == link.provider:
                id_link_exists = True
            elif "google" == link.provider:
                google_link_exists = True
            elif "github" == link.provider:
                github_link_exists = True
            elif "facebook" == link.provider:
                facebook_link_exists = True
    except Exception as e:
        sentry_sdk.capture_exception(e)

    return render_template("settings.html",
                           user_id=user_id,
                           user_name=user.first_name,
                           user_language=user.language,
                           in_family=is_in_family,
                           in_group=is_in_group,
                           families=user_families,
                           groups=user_groups,
                           title=_("Settings"),
                           id_connected=id_link_exists,
                           google_connected=google_link_exists,
                           github_connected=github_link_exists,
                           facebook_connected=facebook_link_exists,
                           group_admin=group_admin,
                           family_admin=family_admin)


@main_page.route("/editfam/<family_id>", methods=["GET"])
@login_required
def editfamily(family_id: str):
    """
    :param family_id: The family to modify
    """
    user_id = int(session["user_id"])

    try:
        family_id = int(family_id)
    except Exception as e:
        sentry_sdk.capture_exception(e)
        return render_template("utility/error.html",
                               message=_("Broken link"),
                               no_sidebar=not current_user.is_authenticated,
                               title=_("Error"))

    db_family_members = UserFamilyAdmin.query.filter(
        UserFamilyAdmin.family_id == family_id).all()

    family = []
    show_admin_column = False
    for member in db_family_members:
        is_admin = False
        is_person = False
        if member.user_id == user_id:
            is_person = True
            if member.admin:
                show_admin_column = True

        if member.admin:
            is_admin = True

        birthday = None
        try:
            birthday = str(User.query.filter(User.id == member.user_id).first().birthday.strftime("%d.%m"))
        except Exception:
            pass

        family.append(
            (User.query.get(member.user_id).first_name, member.user_id, is_admin, is_person, birthday))

    return render_template("editfam.html",
                           family=family,
                           title=_("Edit family"),
                           admin=show_admin_column,
                           family_id=family_id)


@main_page.route("/setlanguage", methods=["POST"])
@login_required
def set_language():
    """
    Allows the user to set their language
    """
    user_id = session["user_id"]
    try:
        if request.form["language"] in ["en", "ee"]:
            user = User.query.filter(User.id == user_id).first()
            try:
                user.language = request.form["language"]
                db.session.commit()
            except Exception as e:
                sentry_sdk.capture_exception(e)
                db.session.rollback()
                return render_template("utility/error.html",
                                       message=_("Faulty input"),
                                       title=_("Error"))

        return render_template("utility/success.html",
                               action=_("Added"),
                               link="./notes",
                               title=_("Added"))
    except Exception:
        # No need to capture with Sentry, someone's just meddling
        return render_template("utility/error.html",
                               message=_("Faulty input"),
                               title=_("Error"))


@main_page.route("/editgroup", methods=["GET"])
@login_required
def editgroup():
    user_id = session["user_id"]
    # user_obj = User.query.get(user_id)

    try:
        group_id = request.args["id"]
        group_id = int(group_id)
    except Exception as e:
        sentry_sdk.capture_exception(e)
        return render_template("utility/error.html",
                               message=_("Faulty input"),
                               title=_("Error"))

    db_families_in_group = get_families_in_group(group_id)

    families = []
    for family in db_families_in_group:
        families.append((family.name, family.id))

    is_admin = False
    if if_user_is_group_admin(group_id, user_id):
        is_admin = True

    return render_template("editgroup.html",
                           title=_("Edit group"),
                           families=families,
                           group_id=request.args["id"],
                           admin=is_admin)


@main_page.route("/editgroup", methods=["POST"])  # TODO: Maybe merge with editgroup
@login_required
def editgroup_with_action():
    user_id = int(session["user_id"])
    endpoint = "editgroup"
    if "action" not in request.form.keys():
        return render_template("utility/error.html",
                               message=_("An error has occured"),
                               title=_("Error"))
    else:
        if request.form["action"] == "REMOVEFAM" and "confirm" not in request.form.keys():
            if "extra_data" in request.form.keys():
                extra_data = request.form["extra_data"]
            else:
                return render_template("utility/error.html",
                                       message=_("An error has occured"),
                                       title=_("Error"))

            if "id" in request.form.keys():
                form_id = request.form["id"]
            else:
                return render_template("utility/error.html",
                                       message=_("An error has occured"),
                                       title=_("Error"))

            return render_template("creatething.html",
                                   action="REMOVEFAM",
                                   endpoint=endpoint,
                                   extra_data=extra_data,
                                   id=form_id,
                                   confirm=True)
        elif request.form["action"] == "REMOVEFAM" and request.form["confirm"] == "True":
            family_id = int(request.form["extra_data"])
            group_id = int(request.form["id"])

            admin_relationship = UserGroupAdmin.query.filter(and_(UserGroupAdmin.group_id == group_id,
                                                                  UserGroupAdmin.user_id == user_id)).one()

            if not admin_relationship.admin:
                logger.warning("User {} is trying to forge requests".format(user_id))
                return render_template("utility/error.html",
                                       message=_("An error has occured"),
                                       title=_("Error"))

            target_relationship = FamilyGroup.query.filter(and_(FamilyGroup.group_id == group_id,
                                                                FamilyGroup.family_id == family_id)).one()

            if target_relationship.admin:
                return render_template("utility/error.html",
                                       message=_("You can not delete an admin from your family"),
                                       title=_("Error"))

            target_relationship.delete()

            try:
                db.session.commit()
            except Exception:
                db.session.rollback()
                return render_template("utility/error.html",
                                       message=_("An error has occured"),
                                       title=_("Error"))

            return render_template("utility/success.html",
                                   action=_("Deleted"),
                                   link="./",
                                   title=_("Deleted"))
        elif request.form["action"] == "ADDFAMILY" and "confirm" not in request.form.keys():
            if "extra_data" in request.form.keys():
                extra_data = request.form["extra_data"]
            else:
                return render_template("utility/error.html",
                                       message=_("An error has occured"),
                                       title=_("Error"))

            if "id" in request.form.keys():
                form_id = request.form["id"]
            else:
                return render_template("utility/error.html",
                                       message=_("An error has occured"),
                                       title=_("Error"))

            return render_template("creatething.html",
                                   action="ADDFAMILY",
                                   endpoint=endpoint,
                                   extra_data=extra_data,
                                   id=form_id,
                                   confirm=True)
        elif request.form["action"] == "ADDFAMILY" and request.form["confirm"] == "True":
            # TODO: Add user to family
            return render_template("utility/success.html",
                                   action=_("Added"),
                                   link="./",
                                   title=_("Added"))
        elif request.form["action"] == "DELETEGROUP" and "confirm" not in request.form.keys():
            if "extra_data" in request.form.keys():
                extra_data = request.form["extra_data"]
            else:
                return render_template("utility/error.html",
                                       message=_("An error has occured"),
                                       title=_("Error"))

            if "id" in request.form.keys():
                form_id = request.form["id"]
            else:
                return render_template("utility/error.html",
                                       message=_("An error has occured"),
                                       title=_("Error"))

            return render_template("creatething.html",
                                   action="DELETEGROUP",
                                   endpoint=endpoint,
                                   id=form_id,
                                   extra_data=extra_data,
                                   confirm=True)
        elif request.form["action"] == "DELETEGROUP" and request.form["confirm"] == "True":
            # TODO: Delete group
            return render_template("utility/success.html",
                                   action=_("Deleted"),
                                   link="./",
                                   title=_("Deleted"))
        else:
            return render_template("utility/error.html",
                                   message=_("An error has occured"),
                                   title=_("Error"))


@main_page.route("/editfam", methods=["POST"])
@login_required
def editfam_with_action():
    """
    Deals with all the possible modifications to a family
    """
    user_id = int(session["user_id"])
    endpoint = "editfam"
    if "action" not in request.form.keys():
        return render_template("utility/error.html",
                               message=_("An error has occured"),
                               title=_("Error"))
    else:
        if request.form["action"] == "REMOVEMEMBER" and "confirm" not in request.form.keys():
            if "extra_data" in request.form.keys():
                extra_data = request.form["extra_data"]
            else:
                return render_template("utility/error.html",
                                       message=_("An error has occured"),
                                       title=_("Error"))

            if "id" in request.form.keys():
                form_id = request.form["id"]
            else:
                return render_template("utility/error.html",
                                       message=_("An error has occured"),
                                       title=_("Error"))

            return render_template("creatething.html",
                                   action="REMOVEMEMBER",
                                   endpoint=endpoint,
                                   id=form_id,
                                   extra_data=extra_data,
                                   confirm=True)
        elif request.form["action"] == "REMOVEMEMBER" and request.form["confirm"] == "True":
            family_id = int(request.form["extra_data"])
            target_id = int(request.form["id"])

            admin_relationship = UserFamilyAdmin.query.filter(and_(UserFamilyAdmin.user_id == user_id,
                                                                   UserFamilyAdmin.family_id == family_id)).one()

            if not admin_relationship.admin:
                logger.warning("User {} is trying to forge requests".format(user_id))
                return render_template("utility/error.html",
                                       message=_("An error has occured"),
                                       title=_("Error"))

            target_relationship = UserFamilyAdmin.query.filter(and_(UserFamilyAdmin.user_id == target_id,
                                                                    UserFamilyAdmin.family_id == family_id))

            if target_relationship.admin:
                return render_template("utility/error.html",
                                       message=_("You can not delete an admin from your family"),
                                       title=_("Error"))

            target_relationship.delete()

            try:
                db.session.commit()
            except Exception:
                db.session.rollback()
                return render_template("utility/error.html",
                                       message=_("An error has occured"),
                                       title=_("Error"))

            return render_template("utility/success.html",
                                   action=_("Deleted"),
                                   link="./",
                                   title=_("Deleted"))
        elif request.form["action"] == "ADDMEMBER" and "confirm" not in request.form.keys():
            if "extra_data" in request.form.keys():
                extra_data = request.form["extra_data"]
            else:
                return render_template("utility/error.html",
                                       message=_("An error has occured"),
                                       title=_("Error"))

            if "id" in request.form.keys():
                form_id = request.form["id"]
            else:
                return render_template("utility/error.html",
                                       message=_("An error has occured"),
                                       title=_("Error"))

            return render_template("creatething.html",
                                   action="ADDMEMBER",
                                   endpoint=endpoint,
                                   id=form_id,
                                   extra_data=extra_data,
                                   confirm=True)
        elif request.form["action"] == "ADDMEMBER" and request.form["confirm"] == "True":
            family_id = int(request.form["extra_data"])
            target_id = int(request.form["id"])

            admin_relationship = UserFamilyAdmin.query.filter(and_(UserFamilyAdmin.user_id == user_id,
                                                                   UserFamilyAdmin.family_id == family_id)).one()

            if not admin_relationship.admin:
                logger.warning("User {} is trying to forge requests".format(user_id))
                return render_template("utility/error.html",
                                       message=_("An error has occured"),
                                       title=_("Error"))

            target_relationship = UserFamilyAdmin(user_id=target_id,
                                                  admin=False,
                                                  family_id=family_id)

            try:
                db.session.add(target_relationship)
                db.session.commit()
            except Exception:
                db.session.rollback()
                return render_template("utility/error.html",
                                       message=_("An error has occured"),
                                       title=_("Error"))
            return render_template("utility/success.html",
                                   action=_("Added"),
                                   link="./",
                                   title=_("Added"))
        elif request.form["action"] == "DELETEFAM" and "confirm" not in request.form.keys():
            if "extra_data" in request.form.keys():
                extra_data = request.form["extra_data"]
            else:
                return render_template("utility/error.html",
                                       message=_("An error has occured"),
                                       title=_("Error"))

            if "id" in request.form.keys():
                form_id = request.form["id"]
            else:
                return render_template("utility/error.html",
                                       message=_("An error has occured"),
                                       title=_("Error"))

            return render_template("creatething.html",
                                   action="DELETEFAM",
                                   endpoint=endpoint,
                                   id=form_id,
                                   extra_data=extra_data,
                                   confirm=True)
        elif request.form["action"] == "DELETEFAM" and request.form["confirm"] == "True":
            target_id = int(request.form["id"])

            admin_relationship = UserFamilyAdmin.query.filter(and_(UserFamilyAdmin.user_id == user_id,
                                                                   UserFamilyAdmin.family_id == target_id)).one()

            if not admin_relationship.admin:
                logger.warning("User {} is trying to forge requests".format(user_id))
                return render_template("utility/error.html",
                                       message=_("An error has occured"),
                                       title=_("Error"))

            Family.query.filter(and_(Family.id == target_id)).one().delete()

            try:
                db.session.commit()
            except Exception:
                db.session.rollback()
                return render_template("utility/error.html",
                                       message=_("An error has occured"),
                                       title=_("Error"))
            return render_template("utility/success.html",
                                   action=_("Deleted"),
                                   link="./",
                                   title=_("Deleted"))
        else:
            return render_template("utility/error.html",
                                   message=_("An error has occured"),
                                   title=_("Error"))


@main_page.route("/addfam", methods=["GET"])
@login_required
def add_family():
    return render_template("creatething.html",
                           row_count=1,
                           endpoint="editfam",
                           label=_("Group ID"))


@main_page.route("/addgroup", methods=["GET"])
@login_required
def add_group():
    return render_template("creatething.html",
                           row_count=1,
                           endpoint="editgroup",
                           label=_("Group ID"))


@main_page.route("/recreategraph", methods=["GET"])
@login_required
def ask_regraph():
    """
    Displays a confirmation page before reshuffling
    """
    if "extra_data" in request.form.keys():
        extra_data = request.form["extra_data"]
        return render_template("creatething.html",
                               action="ADD",
                               endpoint="recreategraph",
                               extra_data=extra_data,
                               confirm=True)
    else:
        return render_template("utility/error.html",
                               message=_("An error has occured"),
                               title=_("Error"))


@main_page.route("/recreategraph", methods=["POST"])
@login_required
def regraph():
    user_id = session["user_id"]
    try:
        event_id = int(request.form["extra_data"])
    except Exception as e:
        sentry_sdk.capture_exception(e)
        return render_template("utility/error.html",
                               message=_("An error has occured"),
                               title=_("Error"))
    family_obj = Family.query.get(family_id)
    time_right_now = datetime.datetime.now()

    database_families = Family.query.filter(
        Family.id.in_(
            set([familygroup.family_id for familygroup in FamilyGroup.query.filter(
                FamilyGroup.family_id == family_obj.id
            ).all()])
        )
    ).all()
    database_all_families_with_members = []
    for db_family in database_families:
        database_family_members = UserFamilyAdmin.query.filter(
            UserFamilyAdmin.family_id == db_family.id).all()
        database_all_families_with_members.append((db_family.id, database_family_members))

    user_id_to_user_number = {}
    user_number_to_user_id = {}
    start_id = 0
    for family_id, db_family in database_all_families_with_members:
        for member in db_family:
            user_number_to_user_id[start_id] = member.user_id
            user_id_to_user_number[member.user_id] = start_id
            start_id += 1

    try:
        if not UserGroupAdmin.query.filter(
                UserGroupAdmin.user_id == int(user_id) and UserGroupAdmin.admin == True).one():
            return render_template("utility/error.html",
                                   message=_("Access denied"),
                                   title=_("Error"))
    except NoResultFound:
        return render_template("utility/error.html",
                               message=_("Access denied"),
                               title=_("Error"))
    except Exception as e:
        sentry_sdk.capture_exception(e)

    families = []
    family_ids_map = {}
    for family_index, (list_family_id, list_family) in enumerate(database_all_families_with_members):
        families.insert(family_index, {})
        for person_index, person in enumerate(list_family):
            family_ids_map[family_index] = list_family_id
            families[family_index][get_person_name(person.user_id)] = user_id_to_user_number[person.user_id]

    families_shuf_ids = {}
    members_to_families = {}
    for family_id, family_members in enumerate(families):
        for person, person_id in family_members.items():
            members_to_families[person_id] = family_id

    families_to_members = {}
    for family_id, family_members in enumerate(families):
        families_to_members[family_id] = set()
        for person, person_id in family_members.items():
            currentset = families_to_members[family_id]
            currentset.update([person_id])

    last_connections = secretsanta.connectiongraph.ConnectionGraph(members_to_families, families_to_members)

    family_group = FamilyGroup.query.filter(FamilyGroup.family_id == family_obj.id).one().group_id
    for group_shuffle in Shuffle.query.filter(Shuffle.group == family_group).all():  # Get last previous shuffles
        last_connections.add(user_id_to_user_number[group_shuffle.giver],
                             user_id_to_user_number[group_shuffle.getter],
                             group_shuffle.year)

    logger.info("{} is the year of Linux Desktop".format(time_right_now.year))

    santa = secretsanta.secretsantagraph.SecretSantaGraph(families_to_members, members_to_families, last_connections)

    shuffled_ids_str = {}
    for connection in santa.generate_connections(time_right_now.year):
        families_shuf_ids[connection.source] = connection.target
        shuffled_ids_str[str(connection.source)] = str(connection.target)

    logger.info(shuffled_ids_str)

    for giver, getter in families_shuf_ids.items():
        # The assumption is that one group shouldn't have more than one shuffle a year active
        # at the same time, there can be multiple with different years
        db_entry_shuffle = Shuffle(
            giver=user_number_to_user_id[giver],
            getter=user_number_to_user_id[getter],
            year=time_right_now.year,
            group=family_group
        )
        try:
            db.session.add(db_entry_shuffle)
            db.session.commit()
        except Exception:
            db.session.rollback()
            try:
                row = Shuffle.query.filter(and_(Shuffle.giver == user_number_to_user_id[giver],
                                                Shuffle.year == time_right_now.year)).one()
                if row.getter != user_number_to_user_id[getter]:
                    row.getter = user_number_to_user_id[getter]
                    db.session.commit()
            except Exception:
                db.session.rollback()

            sentry_sdk.capture_exception(e)

    return render_template("utility/success.html",
                           action=_("Generated"),
                           link="./notes",
                           title=_("Generated"))


@main_page.route("/testmail")
@login_required
def test_mail():
    from main import mail
    with mail.connect() as conn:
        logger.info("Mail verify: {}".format(conn.configure_host().vrfy))
        msg = Message(recipients=["root@localhost"],
                      body="test",
                      subject="test2")

        conn.send(msg)
    return render_template("utility/success.html",
                           action=_("Sent"),
                           link="./testmail",
                           title=_("Sent"))


@main_page.route("/api/login", methods=["POST"])
def api_login():
    """
    Allows login without CSRF protection if one knows the API key
    """
    username = ""
    try:
        email = request.form["email"]  # TODO: Use header
        password = request.form["password"]
        apikey = request.headers["X-API-Key"]
        if apikey != Config.PRIVATE_API_KEY:
            return "{\"error\": \"error\"}", {"content-type": "text/json"}

        user = User.query.filter(User.email == email).first()

        if verify_password(password, user.password):
            login_user(user)
        else:
            return "{\"error\": \"error\"}", {"content-type": "text/json"}

        return redirect("/")
    except Exception as e:
        sentry_sdk.capture_exception(e)
        logger.info("API login failed for user {}".format(username))
        return "{\"error\": \"error\"}", {"content-type": "text/json"}


if Config.GOOGLE_OAUTH:
    google_blueprint = make_google_blueprint(
        scope=[
            "https://www.googleapis.com/auth/userinfo.email",
            "openid"
        ],
        client_id=Config.GOOGLE_OAUTH_CLIENT_ID,
        client_secret=Config.GOOGLE_OAUTH_CLIENT_SECRET,
        redirect_url="https://" + Config.SERVER_NAME + "/login"
    )
    google_blueprint.backend = SQLAlchemyStorage(AuthLinks, db.session, user=current_user)
    app.register_blueprint(google_blueprint, url_prefix="/google")


    @oauth_authorized.connect_via(google_blueprint)
    def google_oauth_handler(blueprint, token):
        """
        Passes the oauth event to the oauth handler
        """
        return oauth_handler(blueprint, token)


    @main_page.route("/googleregister")
    def google_signup():
        """
        Sets the required session variable to enable signup when logging in
        """
        session["oauth_sign_up"] = True
        return redirect(url_for("google.login"))


    @main_page.route("/googlelogin")
    def google_login():
        """
        Allows someone to just log in with the OAuth provider
        """
        session["oauth_sign_up"] = False
        return redirect(url_for("google.login"))

if Config.GITHUB_OAUTH:
    github_blueprint = make_github_blueprint(
        scope=["user:email"],
        client_id=Config.GITHUB_OAUTH_CLIENT_ID,
        client_secret=Config.GITHUB_OAUTH_CLIENT_SECRET,
        redirect_url="https://" + Config.SERVER_NAME + "/login"
    )
    github_blueprint.backend = SQLAlchemyStorage(AuthLinks, db.session, user=current_user)
    app.register_blueprint(github_blueprint, url_prefix="/github")


    @oauth_authorized.connect_via(github_blueprint)
    def github_oauth_handler(blueprint, token):
        """
        Passes the oauth event to the oauth handler
        """
        return oauth_handler(blueprint, token)


    @main_page.route("/githublogin")
    def github_login():
        """
        Allows someone to just log in with the OAuth provider
        """
        session["oauth_sign_up"] = False
        return redirect(url_for("github.login"))


    @main_page.route("/githubregister")
    def github_signup():
        """
        Sets the required session variable to enable signup when logging in
        """
        session["oauth_sign_up"] = True
        return redirect(url_for("github.login"))

if Config.FACEBOOK_OAUTH:
    facebook_blueprint = make_facebook_blueprint(
        scope=["email"],
        client_id=Config.FACEBOOK_OAUTH_CLIENT_ID,
        client_secret=Config.FACEBOOK_OAUTH_CLIENT_SECRET,
        redirect_url="https://" + Config.SERVER_NAME + "/login"
    )
    facebook_blueprint.backend = SQLAlchemyStorage(AuthLinks, db.session, user=current_user)
    app.register_blueprint(facebook_blueprint, url_prefix="/facebook")


    @oauth_authorized.connect_via(facebook_blueprint)
    def facebook_oauth_handler(blueprint, token):
        """
        Passes the oauth event to the oauth handler
        """
        return oauth_handler(blueprint, token)


    @main_page.route("/facebookregister")
    def facebook_signup():
        """
        Sets the required session variable to enable signup when logging in
        """
        session["oauth_sign_up"] = True
        return redirect(url_for("facebook.login"))


    @main_page.route("/facebooklogin")
    def facebook_login():
        """
        Allows someone to just log in with the OAuth provider
        """
        session["oauth_sign_up"] = False
        return redirect(url_for("facebook.login"))


def oauth_handler(blueprint, token):
    """
    Handles incoming OAuth events, login, signup

    :param blueprint:
    :param token:
    :return:
    """
    if token is None:  # Failed
        logger.info("Failed to log in with {}.".format(blueprint.name))
        flash(_("Error logging in"))
        return False

    try:
        if blueprint.name == "github":
            response = blueprint.session.get("/user")
        elif blueprint.name == "google":
            response = blueprint.session.get("/plus/v1/people/me")
        elif blueprint.name == "facebook":
            response = blueprint.session.get("/me?fields=email")
        else:
            logger.critical("Missing blueprint handler for {}".format(blueprint.name))
            flash(_("Error logging in"))
            return False
    except ValueError as e:
        sentry_sdk.capture_exception(e)
        flash(_("Error logging in"))
        return False

    if not response.ok:  # Failed
        logger.info("Failed to fetch user info from {}.".format(blueprint.name))
        logger.info(response)
        flash(_("Error logging in"))
        return False

    response = response.json()
    oauth_user_id = response["id"]  # Get user ID

    try:  # Check if existing service link
        authentication_link = AuthLinks.query.filter_by(
            provider=blueprint.name,
            provider_user_id=str(oauth_user_id),
        ).one()
    except NoResultFound:  # New service link, at least store the token
        authentication_link = AuthLinks(
            provider=blueprint.name,
            provider_user_id=str(oauth_user_id),
            token=token["access_token"],
        )
        logger.info("User not found, keeping token in memory")
    except Exception as e:  # Failure in query!
        sentry_sdk.capture_exception(e)
        logger.error("Failed querying authentication links")
        flash(_("That account is not linked to any system account, check if you already have an account."))
        return False

    # Link exists and it is associated with an user
    if authentication_link is not None and authentication_link.user_id is not None:
        login_user(User.query.get(authentication_link.user_id))
        db.session.commit()
        logger.info("Successfully signed in with {}.".format(blueprint.name))
        return False
    elif authentication_link is not None and \
            authentication_link.user_id is None and \
            "user_id" in session.keys():
        try:
            authentication_link.user_id = int(session["user_id"])  # Update link with user id
            db.session.add(authentication_link)
            db.session.commit()
            return False
        except Exception as e:
            db.session.rollback()
            sentry_sdk.capture_exception(e)
            logger.error("Could not store user and oauth link")
            flash(_("Error signing up, please try again"))
            return False
    else:  # Link does not exist or not associated
        if "oauth_sign_up" in session.keys() and \
                session["oauth_sign_up"]:  # If registration

            session["oauth_sign_up"] = False
            if "email" in response.keys():
                user_email = response["email"]
            else:
                if "emails" in response.keys() and len(response["emails"]) > 0:
                    user_email = response["emails"][0]["value"]
                else:
                    user_email = None

            if "name" in response.keys():
                if blueprint.name == "google":
                    if "givenName" in response["name"].keys():
                        user_name = response["name"]["givenName"]
                    else:
                        logger.info("Google user does not have a givenName")
                        flash(_("Error signing up"))
                        return False
                else:
                    user_name = response["name"]
            else:
                logger.info("User does not have a name!")
                flash(_("Error signing up"))
                return False

            if user_email is None or \
                    len(user_email) < len("a@b.cc") or \
                    "@" not in user_email:  # I'll assume noone with their own TLD will use this
                logger.info("User email is wrong or missing, trying other API endpoint")
                try:
                    if blueprint.name == "github":  # If we're authenticating against GitHub then we have to do
                        # another get
                        response = blueprint.session.get("/user/emails")
                        if not response.ok:
                            flash(_("Error signing up"))
                            logger.info("Error requesting email addresses")
                            return False
                        else:
                            response = response.json()
                            user_email = response[0]["email"] if len(response) > 0 and \
                                                                 "email" in response[0].keys() else None
                            # Take the first email
                            if not response[0]["verified"] or \
                                    user_email is None or \
                                    len(user_email) < len("a@b.cc") or \
                                    "@" not in user_email:
                                flash(_("You have no associated email addresses with your account"))
                                logger.error("User does not have any emails")
                                return False
                            else:
                                pass  # All is okay again
                            pass  # New email is fine
                    else:
                        logger.info("No email addresses associated with the account")
                        flash(_("You have no associated email addresses with that account"))
                        return False
                except Exception:
                    logger.info("Error asking for another emails")
                    flash(_("Error signing up"))
                    return False
            else:
                pass  # Email is okay

            try:  # Check if existing service link
                User.query.filter(User.email == user_email).one()
                flash(_("This email address is in use, you must log in with your password to link {provider}"
                        .format(provider=blueprint.name)))
                logger.debug("Email address is in use, but not linked, to avoid hijacks the user must login")
                return False
            except NoResultFound:  # Do not allow same email to sign up again
                pass

            user = User(
                email=user_email,
                username=user_name,
                password=hash_password(token_bytes(100)),
                active=True
            )
            flash(_("Password is set randomly, use \"Forgot password\" to set another password"))

            try:
                db.session.add(user)  # Populate User's ID first by committing
                db.session.commit()
            except Exception as e:
                db.session.rollback()
                sentry_sdk.capture_exception(e)
                logger.error("Could not store user and oauth link")
                flash(_("Error signing up"))
                return False

            try:
                authentication_link.user_id = user.id  # Update link with user id
                db.session.add(authentication_link)
                db.session.commit()
            except Exception as e:
                db.session.rollback()
                sentry_sdk.capture_exception(e)
                logger.error("Could not store user and oauth link")
                flash(_("Error signing up"))
                return False

            login_user(user)
            db.session.commit()
            logger.info("Successfully signed up with {}.".format(blueprint.name))
            return False
        else:
            logger.debug("User does not wish to sign up")
            flash(_("You do not have an account"))
            return False


@main_page.route("/clientcert")
def log_user_in_with_cert():
    """
    This functionality requires another subdomain requiring client cert

    Nginx configuration for TLC client certificate authentication (Estonian ID card authentication)
    ```
    proxy_set_header Tls-Client-Secret Config.TLS_PROXY_SECRET;
    proxy_set_header Tls-Client-Verify $ssl_client_verify;
    proxy_set_header Tls-Client-Dn     $ssl_client_s_dn;
    proxy_set_header Tls-Client-Cert   $ssl_client_cert;
    ```
    """
    if "Tls-Client-Secret" in request.headers.keys():
        logger.debug("Tls-Client-Secret exists")
        if Config.TLS_PROXY_SECRET in request.headers["Tls-Client-Secret"]:
            logger.debug("Tls-Client-Secret is correct")
            if "Tls-Client-Verify" in request.headers.keys():
                logger.debug("Tls-Client-Verify exists")
                if "SUCCESS" in request.headers["Tls-Client-Verify"]:
                    logger.debug("Tls-Client-Verify is correct")
                    if "Tls-Client-Dn" in request.headers.keys():
                        logger.debug("Tls-Client-Dn exists")
                        if session:
                            logger.debug("Session exists")
                            if "user_id" in session.keys():
                                logger.debug("User ID exists")
                                hashed_dn = get_sha3_512_hash(get_id_code(request.headers["Tls-Client-Dn"]))
                                link = AuthLinks.query.filter(and_(AuthLinks.provider_user_id == hashed_dn,
                                                                   AuthLinks.provider == "esteid")).first()

                                if link is not None:
                                    return redirect("/")

                                link = session["user_id"]
                                new_link = AuthLinks(
                                    user_id=int(link),
                                    provider_user_id=hashed_dn,
                                    token=None,
                                    provider="esteid"
                                )
                                try:
                                    db.session.add(new_link)
                                    db.session.commit()
                                except Exception as e:
                                    logger.debug("Error adding link")
                                    db.session.rollback()
                                    db.session.commit()
                                    sentry_sdk.capture_exception(e)
                                    return redirect("/error?message=" + _("Error!") + "&title=" + _("Error"))
                                return redirect("/")
                            else:
                                logger.debug("User ID doesn't exist")
                                return try_to_log_in_with_dn(request.headers["Tls-Client-Dn"])
                        else:
                            return try_to_log_in_with_dn(request.headers["Tls-Client-Dn"])
    logger.debug("Check failed")
    return redirect("error?message=" + _("Error!") + "&title=" + _("Error"))


def try_to_log_in_with_dn(input_dn: str) -> object:
    """
    This function allows people to log in based on the hash of the DN of their certificate
    Assumes certificate validity, which also means that the issuing CA has been checked and whitelisted
    Most likely a new ID-card requires new link to be made to log in
    This is a tradeoff unless someone wants to start to store Personal Identification Numbers and parse DNs

    :param input_dn: The DN field of the client certificate
    :return: Returns a redirect depending on result
    """
    try:
        hashed_dn = get_sha3_512_hash(get_id_code(input_dn))
        link = AuthLinks.query.filter(and_(AuthLinks.provider_user_id == hashed_dn,
                                           AuthLinks.provider == "esteid")).first()
        if link is not None:
            user_id = link.user_id
        else:
            hashed_dn = get_sha3_512_hash(input_dn)  # Legacy hashing
            link = AuthLinks.query.filter(and_(AuthLinks.provider_user_id == hashed_dn,
                                               AuthLinks.provider == "esteid")).first()
            if not link:
                logger.debug("User with the link doesn't exist")
                return redirect("/error?message=" + _("Error!") + "&title=" + _("Error"))
            else:
                user_id = link.user_id

        login_user(User.query.get(user_id))
        return redirect("/success.html?" + "message=" + _("Added!") + "&action=" +
                        _("Added") + "&link=" + "notes" + "&title=" + _("Added"))
    except Exception as e:
        logger.debug("Exception when trying to log user in")
        sentry_sdk.capture_exception(e)
        return redirect("/error?message=" + _("Error!") + "&title=" + _("Error"))


# noinspection PyUnresolvedReferences
import views_generic
# noinspection PyUnresolvedReferences
import background
