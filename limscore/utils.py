import pdb
from functools import wraps

from flask import session, request, url_for, current_app, redirect
from werkzeug.exceptions import Conflict, Forbidden, BadRequest

from sqlalchemy import select, join, and_, or_
from sqlalchemy.exc import IntegrityError

from .models import logins



_navbars = {}
valid_groups = set(["Admin.Administrator", "External.View"])



def as_navbar(section):
    def login_decorator(function):
        _navbars[section] = function
        return function
    return login_decorator



def navbar(active=None):
    section = session.get("section", "")
    if "TITLE" in current_app.config:
        title = current_app.config["TITLE"].format(section)
    else:
        title = section
    if section not in ("Admin", "External"):
        site = session.get("site", "")
    else:
        site = ""
    return  {"title": title,
             "site":  site,
             "active": active, 
             "menuitems": _navbars.get(section, lambda:())()}



def login_required(*groups, ajax_or_new_tab=False):
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
                return redirect(url_for("admin.login"))
            
            if request.method == "POST" and \
               request.form.get("csrf", default="") != session["csrf"]:
                return redirect(url_for("admin.logout"))
            
            if group_names and session["group"] not in group_names:
                if request.method == "POST":
                    abort(Forbidden)
                
                elif section_names and session["section"] not in section_names:
                    return redirect(url_for("admin.root"))
            
            if not ajax_or_new_tab:
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



def tablerow(*args, deleted=False, **kwargs):
    if deleted:
        kwargs["class"] = "deleted {}".format(kwargs.get("class", ""))
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
        return url_for("admin.root")
    args["dir"] = steps
    return url_for(endpoint, **args)



def url_fwrd(*args, **kwargs):
    return url_for(*args, dir=1, **kwargs)



def strftime(val, formatstring="%d %b %Y"):
    try:
        return val.strftime(formatstring)
    except AttributeError:
        return ""
    


def initial_surname(forename, surname):
    if forename:
        return "{}.{}".format(forename[0], surname)
    return surname or ""
    


def surname_forename(surname, forename):
    if forename:
        return "{}, {}".format(surname, forename)
    return surname or ""



def account(name, conn):
    sql = select([logins.c.username, logins.c.password, logins.c.info]). \
            where(logins.c.name == name)
    row = conn.execute(sql).first() or ()
    if row:
        row = dict(row)
        for keyval in row.pop("info").split("|"):
            keyval = keyval.split("=")
            if len(keyval) == 2:
                row[keyval[0].lower()] = keyval[1]
    return row
