import pdb
import datetime
from functools import wraps
from collections import defaultdict

from dateutil import parser
import pytz

from flask import session, request, url_for, current_app, redirect
from flask.sessions import SecureCookieSessionInterface
import flask
from werkzeug.exceptions import Conflict, Forbidden, BadRequest, InternalServerError

from sqlalchemy.exc import IntegrityError

from .i18n import _


__all__ = ["utcnow",
           "login_required",
           "engine",
           "abort",
           "tablerow",
           "is_valid_nhs_number",
           "url_fwrd",
           "url_back",
           "initial_surname",
           "surname_forename",
           "render_template",
           "render_page",
           "navbar",
           "sign_cookie",
           "unique_violation_or_reraise",
           "iso8601_to_utc"]



_navbars = defaultdict(lambda:lambda:())
valid_groups = set(["Admin.Administrator"])



def iso8601_to_utc(dt_string):
    """ Convert a string in iso8601 format to a datetime with the timezone set
        to UTC.
    """
    dt = parser.isoparse(dt_string)
    return dt.astimezone(pytz.utc)



def render_template(name, style=None, **kwargs):
    """ Adds correct prefix to template supplied to flask.render_template.
        Enables swapping of css styles on the fly.
    """
    if style is None:
        style = current_app.config.get("STYLE", None)
    if style is not None:
        name = f"{style}/{name}"
    return flask.render_template(name, **kwargs)



def render_page(name, active=None, **context):
    """ Wrapper around flask.render_template to add appropriate navbar context
        before calling flask.render_template itself. To be used instead of 
        flask.render_template when rendering a full page. Not to be used for
        ajax calls for dropdowns etc.
    """
    config = current_app.config
    application = config.get("NAME", "")
    if "id" not in session:
        navbar = {"app": application}
    else:
        section = session.get("section", "")

        right = [{"text": _("Help"),
                  "href": url_for("auth.site_menu")},
                 {"text": session.get("project", ""),
                  "href": url_for("auth.project_menu"),
                  "dropdown": True},
                 {"text": session.get("site", ""),
                  "href": url_for("auth.site_menu"),
                  "dropdown": True},
                 {"text": "",
                  "href": url_for("auth.logout_menu"),
                  "dropdown": True}]
        navbar = {"app": application,
                  "section": section,
                  "active": active,
                  "left": _navbars[section](),
                  "right": right}
    return render_template(name, navbar=navbar, **context)



def utcnow():
    """ Returns current datetime with timezone set to UTC. Assumes that the
        server is running on UTC time which is the only sensible configuration
        anyway.
    """
    return datetime.datetime.now(tz=datetime.timezone.utc)



def navbar(section):
    """ Decorator to register a new navbar menu.
    """
    def decorator(function):
        _navbars[section] = function
        return function
    return decorator



def login_required(*groups, history=True):
    """Decorator to protect every view function (except login, set_password,
        etc that are called before user is logged in). Group names are in the
        format Section.Role. If no groups are provided then this endpoint can
        be viewed and written to by anyone although the actual records they
        can access can still be limited by filtering database queries on their
        current Section and/or Role within the view. If a Role is provided
        then the endpoint can be viewed by anyone but only written to by a
        user currently holding that Role. If a Section is provided then that
        endpoint can only be viewed by users currently holding that Section.
        Also provides navigation support by storing the url for use by the
        url_back function.
        
        All view functions MUST be protected with this decorator.
        
        *** WARNING Writable endpoints that have no groups specified MUST 
        protect against writes by users with the view function itself by 
        database filtering of choices supplied to forms as even though 
        these views will never be directly accessable from the navbar the
        url could be hand entered by a malicious user. ***

    Args:
        groups (list of str): Groups allowed to make a request to this 
            endpoint.
        ajax_or_new_tab (bool): If True then this request is outside of
            normal navigation and should not be added to the navigation 
            stack.
        
    Returns:
        None
        
    Raises:
        Forbidden if users group does not match the required permissions for
        this endpoint.
        Conflict if a database IntegrityError occurs during datbase access.
        All other exceptions are passed through unmodified.
        
     """
    def login_decorator(function):
        section_names = []
        group_names = []
        for group in groups:
            split_group = group.split(".")
            if len(split_group) != 2:
                raise RuntimeError("Invalid group name {}".format(group))
            section = split_group[0]
            if split_group[1]:
                valid_groups.add(group)
                group_names += [group]
            else:
                section_names += [section]

        @wraps(function)
        def wrapper(*args, **kwargs):
            if "id" not in session:
                return redirect(url_for("auth.login"))
            
            if group_names and session["group"] not in group_names:
                if request.method == "POST":
                    abort(Forbidden)
                
                elif section_names and session["section"] not in section_names:
                    return redirect(url_for("auth.root", dir=0))
            
            if history:
                store_history()
            
            try:
                return function(*args, **kwargs)
            except IntegrityError:
                abort(Conflict)
        return wrapper
    return login_decorator
    


class _ProxyEngine(object):
    def __getattr__(self, name):
        return getattr(current_app.extensions["engine"], name)
engine = _ProxyEngine()

    
    
def abort(exc):
    raise exc
        


def is_valid_nhs_number(data):
    if len(data) == 10 and data.isnumeric():
        val = 11 - (sum(int(x)*y for x, y in zip(data[:9], range(10, 1, -1))) % 11)
        if val == 11:
            val = 0
        if val == int(data[9]):
            return data



def tablerow(*args, **kwargs):
    return (args, kwargs)



def store_history():
    """Stores navigation history to allow back button functionality. Is called
        before every view by the login_required decorator unless 
        ajax_or_new_tab=True.
        url_for() is called with an additional dir argument to specify the
        navigation direction.
        dir = 1 for forward navigation.
        dir = 0 to reset the navigation stack to the top level ie navbar.
        dir omitted for sideways navigation.
        dir <= -1 for backwards navigation.

    Args:
        None
        
    Returns:
        None
        
    Raises:
        Will never raise an exception
        
    """
    endpoints = session.get("endpoints", [])
    request_args = request.args.to_dict()
    direction = request_args.get("dir", None)
    
    if direction is None: # sideways navigation
        # replace last endpoint with current endpoint
        endpoints = endpoints[:-1]
    
    elif direction == "0": # reset navigation stack
        endpoints = []
        
    else: # forwards or backwards navigation
        endpoint = request.endpoint
        for i in range(len(endpoints)-1, -1, -1):
            if endpoints[i][0] == endpoint:
                endpoints = endpoints[:i]
                break
            
    endpoint = (request.endpoint, {**request.view_args, **request_args})
    session["endpoints"] = endpoints + [endpoint]
    
    
    
def url_back(steps=-1):
    try:
        endpoint, args = session["endpoints"][steps-1]
    except (KeyError, IndexError):
        return url_for("auth.root", dir=0)
    args["dir"] = steps
    return url_for(endpoint, **args)



def url_fwrd(*args, **kwargs):
    return url_for(*args, dir=1, **kwargs)



def back_exists():
    return len(session["endpoints"]) > 1
    
    

def initial_surname(forename, surname):
    if forename:
        return "{}.{}".format(forename[0], surname)
    return surname or ""
    


def surname_forename(surname, forename):
    if forename:
        return "{}, {}".format(surname, forename)
    return surname or ""



def sign_cookie(data):
    session_serializer = SecureCookieSessionInterface() \
                         .get_signing_serializer(current_app)
    return session_serializer.dumps(dict(session))



def unique_violation_or_reraise(e):
    db_url = current_app.config["DB_URL"]
    if db_url.startswith("postgresql"):
        msg = repr(e.orig)
        if msg.startswith("UniqueViolation"):
            return msg.split("DETAIL:  Key (")[1].split(")")[0]
        
    elif db_url.startswith("sqlite://"):
        # Need to confirm this works.
        msg = e._message()
        if " UNIQUE constraint failed: " in msg:
            return msg.split(" UNIQUE constraint failed: ")[1].split(".")[1]

    raise e
    
    
    
    
    
    
    
    
    
    
    
