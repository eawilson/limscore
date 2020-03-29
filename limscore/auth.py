import pdb
import pytz
from ipaddress import (ip_address,
                       ip_network)

from sqlalchemy import (select,
                        join,
                        or_,
                        and_)

from flask import (session,
                   redirect,
                   url_for,
                   request,
                   abort,
                   Blueprint,
                   current_app)

from werkzeug.exceptions import (Conflict,
                                 Forbidden,
                                 BadRequest,
                                 InternalServerError)

from passlib.hash import bcrypt_sha256
from itsdangerous import URLSafeTimedSerializer

from .models import (users,
                     groups,
                     users_groups,
                     sites,
                     users_sites,
                     projects,
                     users_projects)
from .forms import (LoginForm,
                   ChangePasswordForm)
from .utils import (render_template,
                    render_page,
                    utcnow,
                    store_history,
                    url_fwrd,
                    url_back,
                    surname_forename,
                    engine,
                    login_required,
                    valid_groups,
                    abort,
                    root_url)
from .mail import MailServer
from . import logic


try:
    from secrets import token_urlsafe
except ImportError: # python < 3.6
    import os, base64
    def token_urlsafe(nbytes=32):
        secret = base64.urlsafe_b64encode(os.urandom(nbytes))
        return secret.rstrip(b'=').decode('ascii')

__all__ = ("app",
           "send_setpassword_email")


app = Blueprint("auth", __name__)



@app.route("/")
def root():
    return redirect(root_url())



@app.route("/login", defaults={"action": "login"}, methods=["GET", "POST"])
@app.route("/login/<any('reset', 'login'):action>", methods=["GET", "POST"])
def login(action):
    with engine.connect() as conn:
        
        # login_token = None if not required for this ip address or 
        #  "" if required but not provided.
        login_token = None
        if "LOGIN_TOKEN" in current_app.config:
            for network in current_app.config["LOGIN_TOKEN"].split(","):
                if bool(setting.startswith("!")) != bool(ip_address(request.remote_addr) in ip_network(network.lstrip("!"))):
                    break
            else:
                login_token = request.args.get("login_token", "")

        feedback = ""
        form = LoginForm(request.form)
        if request.method == "POST":
            session.clear()
            if form.validate():
                name = form.username.data
                sql = select([users.c.id, users.c.username, users.c.password, users.c.email, users.c.history]). \
                        where(and_(or_(users.c.username == name, users.c.email == name), users.c.deleted == False)). \
                        order_by(users.c.email == name)
                if login_token is not None:
                    sql = sql.where(users.c.login_token == login_token)
                rows = list(conn.execute(sql))
                
                if action == "login":
                    for row in rows:
                        if form.password.data and bcrypt_sha256.verify(form.password.data, row["password"] or ""):
                            user_id = row[users.c.id]
                            session["id"] = user_id
                            session["csrf"] = token_urlsafe(64)
                            try:
                                session["timezone"] = pytz.timezone(form.timezone.data).zone
                            except pytz.exceptions.UnknownTimeZoneError:
                                session["timezone"] = "UTC"
                            history = row[users.c.history]

                            sql = select([groups.c.name]). \
                                    select_from(join(groups, users_groups, groups.c.id == users_groups.c.group_id)). \
                                    where(users_groups.c.user_id == user_id). \
                                    order_by(groups.c.name != history.get("group", ""), groups.c.id)
                            group = conn.execute(sql).scalar()
                            if group is not None:
                                session["group"] = group
                                session["section"] = group.split(".")[0]

                                sql = select([sites.c.id, sites.c.name]). \
                                        select_from(join(sites, users_sites, sites.c.id == users_sites.c.site_id)). \
                                        where(users_sites.c.user_id == user_id). \
                                        order_by(sites.c.id != history.get("site_id", 0), sites.c.id)
                                row = conn.execute(sql).first()
                                if row is not None:
                                    session["site_id"], session["site"] = row
                                    
                                sql = select([projects.c.id, projects.c.name]). \
                                        select_from(join(projects, users_projects, projects.c.id == users_projects.c.project_id)). \
                                        where(users_projects.c.user_id == user_id). \
                                        order_by(projects.c.id != history.get("project_id", 0), projects.c.id)
                                row = conn.execute(sql).first()
                                if row is not None:
                                    session["project_id"], session["project"] = row
                                
                                return(redirect(root_url()))

                        form.password.errors = "Invalid username/password combination."
                
            elif action == "reset" and current_app.config.get("EMAIL", False):
                if rows and rows[0][users.c.email]:
                    send_setpassword_email(rows[0], conn)
                feedback = ["Please check your inbox for password reset email."]
        
    if current_app.config.get("EMAIL", False):
        reset_url = url_for(".login", action="reset", login_token=login_token)
        reset = ("Reset Password", reset_url)
    else:
        reset = None
    submit = ("Login", url_for(".login", login_token=login_token))
    return render_page("login.html", form=form, submit=submit, reset=reset, feedback=feedback)



@app.route("/logoutmenu")
@login_required(history=False)
def logout_menu():
    menu = []
    with engine.connect() as conn:
        sql = select([groups.c.id, groups.c.name]). \
                select_from(join(groups, users_groups, 
                                    groups.c.id == users_groups.c.group_id)). \
                where(and_(users_groups.c.user_id == session["id"],
                            groups.c.name != session["group"],
                            groups.c.name.in_(valid_groups))). \
                order_by(groups.c.name)
        rows = [{"text": name, "href": url_fwrd(".setrole", group_id=group_id)} for group_id, name in conn.execute(sql)]
        if rows:
            menu += [{"text": "Change Role"}] + rows + [{"divider": True}]
            
    menu += [{"text": "Change Password", "href": url_fwrd(".change_password")},
             {"divider": True},
             {"text": "Logout", "href": url_for(".logout")}]
    return render_template("dropdown.html", items=menu)



@app.route("/setrole/<int:group_id>")
@login_required()
def setrole(group_id):
    with engine.begin() as conn:
        sql = select([groups.c.name, users.c.history]). \
                select_from(join(groups, users_groups, 
                                groups.c.id == users_groups.c.group_id). \
                            join(users, users.c.id == users_groups.c.user_id)). \
                where(and_(users_groups.c.user_id == session["id"],
                           groups.c.id == group_id,
                           groups.c.name.in_(valid_groups)))
        row = conn.execute(sql).first()
        if row:
            group, history = row
            section = group.split(".")[0]
            same_section = session["section"] == section
            session["group"] = history["group"] = row[0]
            session["section"] = section
            conn.execute(users.update().where(users.c.id == session["id"]).values(history=history))
            return redirect(url_back() if same_section else root_url())
    return redirect(url_for(".logout"))



@app.route("/logout")
@login_required()
def logout():
    with engine.connect() as conn:
        login_token = conn.execute(select([users.c.login_token]).where(users.c.id == session["id"])).first()
    session.clear()
    return redirect(url_for(".login", login_token=login_token))



@app.route("/sitemenu")
@login_required(history=False)
def site_menu():
    menu = []
    with engine.connect() as conn:
        sql = select([sites.c.id, sites.c.name]). \
                select_from(join(sites, users_sites, 
                                    sites.c.id == users_sites.c.site_id)). \
                where(and_(users_sites.c.user_id == session["id"],
                           sites.c.deleted == False)). \
                order_by(sites.c.name)
        rows = [{"text": name, "href": url_fwrd(".setsite", site_id=site_id)}
                for site_id, name in conn.execute(sql)
                if site_id != session.get("site_id", None)]
    if rows:
        menu += [{"text": "Switch Site"}] + rows
    return render_template("dropdown.html", items=menu)



@app.route("/setsite/<int:site_id>")
@login_required()
def setsite(site_id):
    with engine.begin() as conn:
        sql = select([sites.c.id, sites.c.name, users.c.history]). \
                select_from(join(sites, users_sites, 
                                sites.c.id == users_sites.c.site_id). \
                            join(users, users.c.id == users_sites.c.user_id)). \
                where(and_(users_sites.c.user_id == session["id"],
                           sites.c.id == site_id,
                           sites.c.deleted == False))
        row = conn.execute(sql).first()
        if row:
            history = row[2]
            session["sie_id"] = history["site_id"] = row[0]
            session["site"] = row[1]
            conn.execute(users.update().where(users.c.id == session["id"]).values(history=history))
    return redirect(url_back())



@app.route("/projectmenu")
@login_required(history=False)
def project_menu():
    menu = []
    with engine.connect() as conn:
        sql = select([projects.c.id, projects.c.name]). \
                select_from(join(projects, users_projects,
                                    projects.c.id == users_projects.c.project_id)). \
                where(and_(users_projects.c.user_id == session["id"],
                           projects.c.deleted == False)). \
                order_by(projects.c.name)
        rows = [{"text": name, "href": url_fwrd(".setproject", project_id=project_id)}
                for project_id, name in conn.execute(sql)
                if project_id != session.get("project_id", None)]
    if rows:
        menu += [{"text": "Switch Project"},
                 {"text": "All Projects", "href": url_fwrd(".setproject")}] + rows
    return render_template("dropdown.html", items=menu)



@app.route("/setproject/all", defaults={"project_id": None})
@app.route("/setproject/<int:project_id>")
@login_required()
def setproject(project_id):
    with engine.begin() as conn:
        if project_id is None:
            sql = select([users.c.history]).where(users.c.id == session["id"])
            history = conn.execute(sql).scalar()
            row = [None, "All Projects", history]
        else:
            sql = select([projects.c.id, projects.c.name, users.c.history]). \
                    select_from(join(projects, users_projects, 
                                        projects.c.id == users_projects.c.project_id). \
                                join(users, users.c.id == users_projects.c.user_id)). \
                    where(and_(users_projects.c.user_id == session["id"],
                            projects.c.id == project_id,
                            projects.c.deleted == False))
            row = conn.execute(sql).first()
        if row:
            history = row[2]
            session["project_id"] = history["project_id"] = row[0]
            session["project"] = row[1]
            conn.execute(users.update().where(users.c.id == session["id"]).values(history=history))
    return redirect(url_back())



@app.route("/changepassword", methods=["GET", "POST"])
@login_required()
def change_password():
    with engine.begin() as conn:
        form = ChangePasswordForm(request.form)
        if request.method == "POST" and form.validate():
            sql = select([users.c.password]). \
                        where(users.c.id == session["id"])
            result = conn.execute(sql).first()
            if result and bcrypt_sha256.verify(form.old_password.data, result[users.c.password]):
                new_data = {"password": bcrypt_sha256.hash(form.password1.data)}
                old_data = {"password": form.old_password.data}
                calculated_values = {"reset_datetime": None}
                logic.admin_edit(users, session["id"], new_data, old_data, conn,
                                 calculated_values=calculated_values)
                return redirect(url_back())
            form.old_password.errors = "Old password incorrect."
        submit = ("Save", url_for(".change_password"))
        back = ("Cancel", url_back())
    return render_page("login.html", form=form, submit=submit, back=back)



@app.route("/setpassword/<string:token>", methods=["GET", "POST"])
def set_password(token):
    with engine.begin() as conn:
        
        try:
            s = URLSafeTimedSerializer(current_app.config['SECRET_KEY'],
                                       salt="set_password")
            user_id, reset_datetime = s.loads(token, max_age=60*60*24*7)
            user_id = conn.execute(select([users.c.id]). \
                        where(and_(users.c.id == user_id, 
                                   users.c.reset_datetime == reset_datetime))). \
                        first()[0]
        except Exception:
            return render_template("modal.html",
                                   form=Form(),
                                   message=["Invalid or expired link."],
                                   navbar=navbar())
        
        form = ChangePasswordForm(request.form)
        del form["old_password"]
        if request.method == "POST" and form.validate():
            login_token = token_urlsafe(64)
            logic.edit_user({"password": bcrypt_sha256.hash(form.password1.data),
                             "reset_datetime": None, 
                             "login_token": login_token},
                            {"id": user_id},
                            conn)
            return redirect(url_for(".login", login_token=login_token))
            
    buttons = (("Save", {"submit": url_for(".set_password", token=token)}),
               ("Cancel", {"href": url_for(".login")}))
    return render_template("form_centred.html",
                           form=form,
                           buttons=buttons,
                           navbar=navbar())



def send_setpassword_email(user, conn):
    reset_datetime = str(utcnow())
    token = URLSafeTimedSerializer(current_app.config['SECRET_KEY'],
                                   salt="set_password"). \
                dumps([user["id"], reset_datetime])
    path = url_for(".set_password", token=token)
    host = dict(request.headers)["Host"]
    link = "http://{}{}".format(host, path)
    name = current_app.config.get("NAME", "Database")
    body = "Username = {}. Please follow {} to reset your {} password. This link can only be used once and will expire in 7 days.".format(user["username"], link, name)
    
    with MailServer(**account("email", conn)) as mailserver:
        mailserver.send(user["email"], "{} Password Link".format(name), body)
    logic.admin_update(users, where=(users.c.id == user["id"]), values=(reset_datetime == reset_datetime), conn=conn)

