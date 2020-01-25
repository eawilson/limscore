import pdb
from datetime import datetime
from functools import wraps
from ipaddress import ip_address, ip_network

from sqlalchemy import select, join, or_, and_
from sqlalchemy.exc import IntegrityError

from flask import render_template, session, redirect, url_for, request, abort, Blueprint, current_app
from werkzeug.exceptions import Conflict, Forbidden, BadRequest, InternalServerError

from passlib.hash import bcrypt_sha256
from itsdangerous import URLSafeTimedSerializer

from .models import users, groups, users_groups, sites
from .forms import LoginForm, ChangePasswordForm, UserEditForm
from .utils import store_history, url_fwrd, url_back, surname_forename, engine, account, navbar, as_navbar, login_required, valid_groups, abort
from .mail import MailServer
from . import logic
from .crud import list_view, crud_route, app

try:
    from secrets import token_urlsafe
except ImportError: # python < 3.6
    import os, base64
    def token_urlsafe(nbytes=32):
        return base64.urlsafe_b64encode(os.urandom(nbytes)).rstrip(b'=').decode('ascii')



__all__ = ("app",)



@as_navbar("Admin")
def admin_navbar():
    return [{"text": "Tables", "href":  url_for("admin.tables_list", dir=0)}]



@app.route("/tables/")
@login_required()
def root():
    navmenu = navbar().get("menuitems", None)
    if navmenu:
        return redirect(navmenu[0]["href"])
    abort(InternalServerError("No navbar defined for section {}.".format(session["section"])))



@app.route("/login", defaults={"action": "login"}, methods=["GET", "POST"])
@app.route("/login/<any('reset', 'login'):action>", methods=["GET", "POST"])
def login(action):
    with engine.connect() as conn:
        
        # login_token = None if not required for this ip address or "" if required but not provided.
        login_token = None
        if "LOGIN_TOKEN" in current_app.config:
            for network in current_app.config["LOGIN_TOKEN"].split(","):
                if bool(setting.startswith("!")) != bool(ip_address(request.remote_addr) in ip_network(network.lstrip("!"))):
                    break
            else:
                login_token = request.args.get("login_token", "")

        form = LoginForm(request.form)
        if request.method == "POST" and form.validate():
            session.clear()
            
            name = form.username.data
            sql = select([users.c.id, users.c.username, users.c.password, users.c.email, sites.c.id, sites.c.name, groups.c.id, groups.c.name]). \
                    select_from(join(users, users_groups, users.c.id == users_groups.c.user_id, isouter=True). \
                                join(groups, and_(groups.c.id == users_groups.c.group_id, groups.c.name.in_(valid_groups))). \
                                join(sites, sites.c.deleted == False, isouter=True)). \
                    where(and_(or_(users.c.username == name, users.c.email == name), users.c.deleted == False)). \
                    order_by(users.c.email == name, groups.c.order, sites.c.id != users.c.last_site_id, sites.c.order)
            if login_token is not None:
                sql = sql.where(users.c.login_token == login_token)
            rows = list(conn.execute(sql))
            
            if action == "reset" and current_app.config.get("EMAIL", False):
                if rows:
                    if rows[0][users.c.email]:
                        send_setpassword_email(rows[0], conn)
                        message = ["Password reset email has been sent."]
                        buttons = (("Continue", {"href": url_for(".login", login_token=login_token)}),)
                        return render_template("modal.html", form=Form(), message=message, buttons=buttons, navbar=navbar())
                    else: # potential for abuse but most friendly option for an internal app
                        form.username.errors = "No email address attached to this account."
                else: # potential for abuse but most friendly option for an internal app
                    form.username.errors = "Unknown username."
            
            else:
                for row in rows:
                    if form.password.data and bcrypt_sha256.verify(form.password.data, row["password"] or ""):
                        session["id"] = row[users.c.id]
                        session["group"] = row[groups.c.name]
                        session["group_id"] = row[groups.c.id]
                        session["section"] = row[groups.c.name].split(".")[0]
                        session["site_id"] = row[sites.c.id]
                        session["site"] = row[sites.c.name]
                        session["csrf"] = token_urlsafe(64)
                        return redirect(url_for(".root"))
                
                # Only intended to be used to bootstrap database and allow creation of a "real" admin account
                if not rows and name == "admin" and form.password.data == "admin" and request.remote_addr == "127.0.0.1":
                    session["id"] = -1
                    session["group"] = "Admin.Administrator"
                    session["section"] = "Admin"
                    return redirect(url_for(".root"))
                    
                form.password.errors = "Invalid username/password combination."
        
    buttons = [("Login", {"submit": url_for(".login", login_token=login_token)})]
    if current_app.config.get("EMAIL", False):
        buttons += [("Reset Password", {"submit": url_for(".login", action="reset", login_token=login_token)})]
    return render_template("form_centred.html", form=form, buttons=buttons, navbar=navbar())



@app.route("/logoutmenu")
def logout_menu():
    menu = []
    if "id" in session:
        with engine.connect() as conn:
            sql = select([groups.c.id, groups.c.name]).select_from(join(groups, users_groups, groups.c.id == users_groups.c.group_id)). \
                    where(and_(users_groups.c.user_id == session["id"], groups.c.name != session["group"], groups.c.name.in_(valid_groups))).order_by(groups.c.name)
            rows = [{"text": name, "href": url_fwrd(".setrole", group_id=group_id)} for group_id, name in conn.execute(sql)]
            if rows:
                menu += [{"header": "Change Role"}] + rows + [{"divider": True}]
                
            if session["section"] not in ("Admin", "External"):
                sql = select([sites.c.id, sites.c.name]). \
                        where(and_(sites.c.id != session.get("site_id", None), sites.c.deleted == False)).order_by(sites.c.order)
                rows = [{"text": name, "href": url_fwrd(".setsite", site_id=site_id)} for site_id, name in conn.execute(sql)]
                if rows:
                    menu += [{"header": "Change Site"}] + rows + [{"divider": True}]
                
        menu += [{"text": "Change Password", "href": url_fwrd(".change_password")}, {"divider": True}]
        menu +=[{"text": "Logout", "href": url_for(".logout")}]
    return render_template("ajax_dropdown.html", items=menu)



@app.route("/logout")
@login_required()
def logout():
    with engine.connect() as conn:
        login_token = conn.execute(select([users.c.login_token]).where(users.c.id == session["id"])).first()
    session.clear()
    return redirect(url_for(".login", login_token=login_token))



@app.route("/setrole/<int:group_id>")
@login_required()
def setrole(group_id):
    with engine.connect() as conn:
        sql = select([groups.c.name, groups.c.id]). \
                select_from(join(users_groups, groups, users_groups.c.group_id == groups.c.id)). \
                where(and_(users_groups.c.user_id == session["id"], users_groups.c.group_id == group_id, groups.c.name.in_(valid_groups)))
        result = conn.execute(sql).first()
        if result:
            section = result[groups.c.name].split(".")[0]
            url = url_back() if session["section"] == section else url_for(".root")
            session["group"] = result[groups.c.name]
            session["group_id"] = result[groups.c.id]
            session["section"] = section
            return redirect(url)
    return redirect(url_for(".logout"))



@app.route("/setsite/<int:site_id>")
@login_required()
def setsite(site_id):
    with engine.begin() as conn:
        sql = select([sites.c.id, sites.c.name]).where(and_(sites.c.id == site_id, sites.c.deleted == False))
        result = conn.execute(sql).first()
        if result:
            session["site_id"] = site_id
            session["site"] = result["name"]
            conn.execute(users.update().where(users.c.id == session["id"]).values(last_site_id=site_id)) # ? move to logic
            return redirect(url_back())
    return redirect(url_for(".logout"))



@app.route("/changepassword", methods=["GET", "POST"])
@login_required()
def change_password():
    with engine.begin() as conn:
        form = ChangePasswordForm(request.form)
        if request.method == "POST" and form.validate():
            result = conn.execute(select([users.c.password]).select_from(users).where(users.c.id == session["id"])).first()
            if result and bcrypt_sha256.verify(form.old_password.data, result[users.c.password]):
                logic.edit_user({"password": bcrypt_sha256.hash(form.password1.data), "reset_datetime": None}, {"id": session["id"]}, conn)
                return redirect(url_back())
            form.old_password.errors = "Old password incorrect."
    return render_template("form_centred.html", form=form, buttons=(("Save", {"submit": url_for(".change_password")}), ("Cancel", {"href": url_back()})), navbar=navbar())



@app.route("/setpassword/<string:token>", methods=["GET", "POST"])
def set_password(token):
    with engine.begin() as conn:
        
        try:
            user_id, reset_datetime = URLSafeTimedSerializer(current_app.config['SECRET_KEY'], salt="set_password").loads(token, max_age=60*60*24*7)
            user_id = conn.execute(select([users.c.id]).where(and_(users.c.id == user_id, users.c.reset_datetime == reset_datetime))).first()[0]
        except Exception:
            return render_template("modal.html", form=Form(), message=["Invalid or expired link."], navbar=navbar())
        
        form = ChangePasswordForm(request.form)
        del form["old_password"]
        if request.method == "POST" and form.validate():
            login_token = token_urlsafe(64)
            logic.edit_user({"password": bcrypt_sha256.hash(form.password1.data), "reset_datetime": None, "login_token": login_token}, {"id": user_id}, conn)
            return redirect(url_for(".login", login_token=login_token))
            
    return render_template("form_centred.html", form=form, buttons=(("Save", {"submit": url_for(".set_password", token=token)}), ("Cancel", {"href": url_for(".login")})), navbar=navbar())


@crud_route()
@login_required("Admin.Administrator", "Admin.")
def users_upsert(row_id=None):
    with engine.begin() as conn:
        sql = select([users.c.id, users.c.forename, users.c.surname, users.c.username, users.c.email, users.c.password, users.c.deleted]). \
                where(users.c.id == row_id)
        old_data = dict(conn.execute(sql).first() or abort(BadRequest)) if row_id is not None else {}
        
        sql = select([groups.c.name, groups.c.id, users_groups.c.user_id]). \
                select_from(join(groups, users_groups, and_(groups.c.id == users_groups.c.group_id, users_groups.c.user_id == row_id, groups.c.name.in_(valid_groups)), isouter=True)). \
                order_by(groups.c.name)
        rows = list(conn.execute(sql))
        old_data["group_id"] = [row[groups.c.id] for row in rows if row[users_groups.c.user_id]]
        group_id_choices = [(row[groups.c.id], row[groups.c.name]) for row in rows]
        if row_id == session["id"]:
            group_id_choices[old_data["group_id"].index(session["group_id"])] += ("disabled",)

        form = UserEditForm(request.form if request.method=="POST" else old_data, group_id_choices=group_id_choices)
        if current_app.config.get("EMAIL", False):
            del form.password
        else:
            form.email.required = False
            if old_data.get("password", None) is not None:
                form.password.required = False
        
        if request.method == "POST":
            if session["group_id"] not in form.group_id.data:
                form.group_id.data += [session["group_id"]]
            if form.validate():
                new_data = form.data
                password = new_data.pop("password", None)
                if password is not None:
                    new_data["password"] = bcrypt_sha256.hash(password)
                
                if row_id == session["id"]:
                    new_data["group_id"] += [session["group_id"]]
                    action = ""
                else:
                    action = request.args.get("action", "")
                    if action == "delete":
                        new_data["deleted"] = True
                        new_data["login_token"] = None
                    elif action == "restore":
                        new_data["deleted"] = False
                
                try:
                    new_data["id"] = logic.edit_user(new_data, old_data, conn)
                    if current_app.config.get("EMAIL", False) and (row_id is None or action == "restore"):
                        send_setpassword_email(new_data, conn)
                    
                    return redirect(url_back())
                except IntegrityError as e:
                    try:
                        form[e._message().split(" UNIQUE constraint failed: ")[1].split(".")[1]].errors = "Must be unique."
                    except (KeyError, IndexError):
                        raise e
    heading = "Edit User" if row_id is not None else "New User"
    buttons=[("Save", {"submit": url_for(".users_upsert", row_id=row_id)}), ("Cancel", {"href": url_back()})]
    if row_id is not None and row_id != session["id"]:
        if not old_data["deleted"]:
            buttons += [("Delete", {"submit": url_for(".users_upsert", row_id=row_id, action="delete"), "class": "float-right", "style": "danger"})]
        else:
            buttons += [("Restore", {"submit": url_fwrd(".users_upsert", row_id=row_id, action="restore"), "class": "float-right", "style": "danger"})]
    return render_template("form.html", form=form, buttons=buttons, heading=heading, navbar=navbar("Users"))



def send_setpassword_email(user, conn):
    reset_datetime = str(datetime.now())
    token = URLSafeTimedSerializer(current_app.config['SECRET_KEY'], salt="set_password").dumps([user["id"], reset_datetime])
    path = url_for(".set_password", token=token)
    host = dict(request.headers)["Host"]
    link = "http://{}{}".format(host, path)
    body = "Username = {}. Please follow {} to reset your integrated database password. This link can only be used once and will expire in 7 days.".format(user["username"], link)
    
    with MailServer(**account("email", conn)) as mailserver:
        mailserver.send(user["email"], "Integrated Password Link", body)
    logic.admin_update(users, where=(users.c.id == user["id"]), values=(reset_datetime == reset_datetime), conn=conn)



@crud_route()
@login_required("Admin.Administrator", "Admin.")
def groups_list():
    return list_view(("Name",groups.c.name))



@crud_route()
@login_required("Admin.Administrator", "Admin.")
def users_list():
    def name(row):
        return surname_forename(row[users.c.surname], row[users.c.forename])
    return list_view(("Name", name),
                     ("Username", users.c.username),
                     ("Email", users.c.email),
                     ("Groups", groups.c.name))




