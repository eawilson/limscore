import time
import base64
import hashlib
import struct
import hmac
import os
import pdb
from io import BytesIO
from urllib.parse import quote

import pytz
import pyqrcode
from babel import Locale

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
                   ChangePasswordForm,
                   TwoFactorForm)
from .utils import (render_template,
                    render_page,
                    utcnow,
                    url_fwrd,
                    url_back,
                    surname_forename,
                    engine,
                    login_required,
                    valid_groups,
                    abort,
                    _navbars)
from .aws import sendmail
from . import logic
from .i18n import _, locale_from_headers



try:
    from secrets import token_urlsafe
except ImportError: # python < 3.6
    def token_urlsafe(nbytes=32):
        secret = base64.urlsafe_b64encode(os.urandom(nbytes))
        return secret.rstrip(b'=').decode('ascii')

__all__ = ("app",
           "send_setpassword_email")


app = Blueprint("auth", __name__)



def hotp(secret, counter, token_length=6):
    try:
        key = base64.b32decode(secret)
    except (base64.binascii.Error, TypeError):
        return -1 # This will never match a true token
    msg = struct.pack(">Q", counter)
    digest = hmac.new(key, msg, hashlib.sha1).digest()
    offset = digest[19] & 15
    number = struct.unpack('>I', digest[offset:offset+4])[0] & 0x7fffffff
    token = number % (10 ** token_length)
    return token



@app.route("/")
@login_required()
def root():
    try:
        return redirect(_navbars[session["section"]]()[0]["href"])
    except (KeyError, IndexError):
        return render_page("base.html")



@app.route("/login", methods=["GET", "POST"])
def login():
    feedback = ""
    form = LoginForm(request.form)
    login_token = request.args.get("login_token", "")
    if login_token:
        del form["authenticator"]
    
    if request.method == "POST":
        session.clear()

        if form.validate():
            feedback = _("Invalid credentials.")
            with engine.connect() as conn:
                email = form.email.data
                sql = select([users.c.id, users.c.password, users.c.totp_secret, users.c.last_session]). \
                        where(and_(users.c.email == email, users.c.deleted == False))
                if login_token:
                    sql = sql.where(users.c.login_token == login_token)
                row = dict(conn.execute(sql).first() or ())
                
                if row and not login_token:
                    code = hotp(row["totp_secret"], int(time.time()) // 30)
                    if form.authenticator.data != code:
                        row = {}
                        
                if row.get("password", None) and \
                        bcrypt_sha256.verify(form.password.data, row["password"]):
                    
                    user_id = row["id"]
                    session["id"] = user_id
                    session["csrf"] = token_urlsafe(64)
                    try:
                        session["timezone"] = pytz.timezone(form.timezone.data).zone
                    except pytz.exceptions.UnknownTimeZoneError:
                        session["timezone"] = "UTC"
                        
                    last_session = row["last_session"]
                    if "group_id" in last_session:
                        setrole(last_session["group_id"])
                    if "site_id" in last_session:
                        setsite(last_session["site_id"])
                    if "project_id" in last_session:
                        setproject(last_session["project_id"])
                    if "locale" in last_session:
                        locale = last_session["locale"]
                    else:
                        locale = locale_from_headers()
                    setlocale(locale)
                    
                    return redirect(url_for(".root", dir=0))
        
    submit = ("Login", url_for(".login", login_token=login_token))
    reset = ("Reset Password", url_for(".reset", login_token=login_token))
    return render_page("login.html", form=form, submit=submit, reset=reset, feedback=feedback)



@app.route("/reset", methods=["GET", "POST"])
def reset():
    feedback = ""
    form = LoginForm(request.form)
    del form["password"]
    login_token = request.args.get("login_token", "")
    if login_token:
        del form["authenticator"]
    if request.method == "POST" and form.validate():
        with engine.connect() as conn:
            email = form.email.data
            sql = select([users.c.id, users.c.password, users.c.totp_secret, users.c.last_session]). \
                    where(and_(users.c.email == email, users.c.deleted == False))
            if login_token:
                sql = sql.where(users.c.login_token == login_token)
            row = dict(conn.execute(sql).first() or ())
            
            if row and not login_token:
                code = hotp(row["totp_secret"], int(time.time()) // 30)
                if form.authenticator.data != code:
                    row = {}
                    
            send_setpassword_email(email, conn)
            feedback = _("Please check your inbox for password reset email.")
        
    submit = ("Reset", url_for(".reset", login_token=login_token))
    back = ("Back", url_for(".login", login_token=login_token))
    return render_page("login.html", form=form, submit=submit, back=back, feedback=feedback)



@app.route("/logoutmenu")
@login_required(history=False)
def logout_menu():
    menu = []
    with engine.connect() as conn:
        sql = select([groups.c.id, groups.c.name]). \
                select_from(join(groups, users_groups, 
                                    groups.c.id == users_groups.c.group_id)). \
                where(and_(users_groups.c.user_id == session["id"],
                            groups.c.name != session.get("group", None),
                            groups.c.name.in_(valid_groups))). \
                order_by(groups.c.name)
        rows = [{"text": name, "href": url_fwrd(".setrole", group_id=group_id)} for group_id, name in conn.execute(sql)]
    if rows:
        menu += [{"text": _("Change Role")}] + rows + [{"divider": True}]
    
    rows = []
    for locale in current_app.extensions["locales"]:
        if locale != session["locale"]:
            rows += [(Locale.parse(locale).get_language_name(locale), locale)]
    if rows:
        menu += [{"text": _("Change Language")}] + \
                [{"text": name, "href": url_fwrd(".setlocale", locale=locale)} for name, locale in sorted(rows)] + \
                [{"divider": True}]
    
    menu += [{"text": _("Change Password"), "href": url_fwrd(".change_password")},
             {"text": _("Two Factor Auth"), "href": url_fwrd(".twofactor")},
             {"divider": True},
             {"text": _("Logout"), "href": url_for(".logout")}]
    return render_template("dropdown.html", items=menu)



@app.route("/setrole/<int:group_id>")
@login_required()
def setrole(group_id):
    with engine.begin() as conn:
        sql = select([groups.c.name, users.c.last_session]). \
                select_from(join(groups, users_groups, 
                                groups.c.id == users_groups.c.group_id). \
                            join(users, users.c.id == users_groups.c.user_id)). \
                where(and_(users_groups.c.user_id == session["id"],
                           groups.c.id == group_id,
                           groups.c.name.in_(valid_groups)))
        row = conn.execute(sql).first()
        if row:
            group, last_session = row
            section = group.split(".")[0]
            same_section = session.get("section", None) == section
            session["group"] = group
            session["section"] = section
            
            if last_session.get("group_id", None) != group_id:
                last_session["group_id"] = group_id
                conn.execute(users.update().where(users.c.id == session["id"]).values(last_session=last_session))
            return redirect(url_back() if same_section else url_for(".root", dir=0))
    return redirect(url_for(".logout"))



@app.route("/logout")
@login_required()
def logout():
    with engine.connect() as conn:
        login_token = conn.execute(select([users.c.login_token]).where(users.c.id == session["id"])).scalar()
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
                           sites.c.id != session.get("site_id", None),
                           sites.c.deleted == False)). \
                order_by(sites.c.name)
        rows = [{"text": name, "href": url_fwrd(".setsite", site_id=site_id)}
                for site_id, name in conn.execute(sql)]
    if rows:
        menu += [{"text": _("Switch Site")}] + rows
    return render_template("dropdown.html", items=menu)



@app.route("/setsite/<int:site_id>")
@login_required()
def setsite(site_id):
    with engine.begin() as conn:
        sql = select([sites.c.name, users.c.last_session]). \
                select_from(join(sites, users_sites, 
                                sites.c.id == users_sites.c.site_id). \
                            join(users, users.c.id == users_sites.c.user_id)). \
                where(and_(users_sites.c.user_id == session["id"],
                           sites.c.id == site_id,
                           sites.c.deleted == False))
        row = conn.execute(sql).first()
        if row:
            site, last_session = row
            session["site_id"] = site_id
            session["site"] = site
            
            if last_session.get("site_id", None) != site_id:
                last_session["site_id"] = site_id
                conn.execute(users.update().where(users.c.id == session["id"]).values(last_session=last_session))
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
                           projects.c.id != session.get("project_id", None),
                           projects.c.deleted == False)). \
                order_by(projects.c.name)
        rows = [{"text": name, "href": url_fwrd(".setproject", project_id=project_id)}
                for project_id, name in conn.execute(sql)]
    if rows:
        menu += [{"text": _("Switch Project")},
                 {"text": _("All Projects"), "href": url_fwrd(".setproject")}] + rows
    return render_template("dropdown.html", items=menu)



@app.route("/setproject/all", defaults={"project_id": None})
@app.route("/setproject/<int:project_id>")
@login_required()
def setproject(project_id):
    with engine.begin() as conn:
        if project_id is None:
            sql = select([users.c.last_session]).where(users.c.id == session["id"])
            last_session = conn.execute(sql).scalar()
            row = [None, _("All Projects"), last_session]
        else:
            sql = select([projects.c.id, projects.c.name, users.c.last_session]). \
                    select_from(join(projects, users_projects, 
                                        projects.c.id == users_projects.c.project_id). \
                                join(users, users.c.id == users_projects.c.user_id)). \
                    where(and_(users_projects.c.user_id == session["id"],
                            projects.c.id == project_id,
                            projects.c.deleted == False))
            row = conn.execute(sql).first()
        if row:
            last_session = row[2]
            session["project_id"] = last_session["project_id"] = row[0]
            session["project"] = row[1]
            conn.execute(users.update().where(users.c.id == session["id"]).values(last_session=last_session))
    return redirect(url_back())



@app.route("/setlocale/<string:locale>")
@login_required()
def setlocale(locale):
    if locale != session.get("locale", None):
        if locale in current_app.extensions.get("locales", ()):
            session["locale"] = locale
        else:
            session["locale"] = "en_GB"
        with engine.begin() as conn:
            sql = select([users.c.last_session]).where(users.c.id == session["id"])
            last_session = conn.execute(sql).scalar()
            if last_session.get("locale", None) != session["locale"]:
                last_session["locale"] = session["locale"]
                conn.execute(users.update().where(users.c.id == session["id"]).values(last_session=last_session))
    return redirect(url_back())



@app.route("/changepassword", methods=["GET", "POST"])
@login_required()
def change_password():
    with engine.begin() as conn:
        form = ChangePasswordForm(request.form)
        if request.method == "POST" and form.validate():
            sql = select([users.c.password]). \
                        where(users.c.id == session["id"])
            old_password = conn.execute(sql).scalar()
            if result and bcrypt_sha256.verify(form.old_password.data, old_password):
                new = {"password": bcrypt_sha256.hash(form.password1.data),
                       "reset_datetime": None}
                old = {"id": session["id"]}
                logic.crud(users, new, old, conn)
                return redirect(url_back())
            form.old_password.errors = _("Old password incorrect.")
        submit = ("Save", url_for(".change_password"))
        back = ("Cancel", url_back())
    return render_page("login.html", form=form, submit=submit, back=back)



@app.route("/setpassword/<string:token>", methods=["GET", "POST"])
def set_password(token):
    with engine.begin() as conn:
        
        try:
            s = URLSafeTimedSerializer(current_app.config['SECRET_KEY'],
                                       salt="set_password")
            email, reset_datetime = s.loads(token, max_age=60*60*24*7)
            user_id = conn.execute(select([users.c.id]). \
                        where(and_(users.c.email == email, 
                                   users.c.reset_datetime == reset_datetime))). \
                        first()[0]
        except Exception:
            return _("Invalid or expired link.")
        
        form = ChangePasswordForm(request.form)
        del form["old_password"]
        if request.method == "POST" and form.validate():
            login_token = token_urlsafe(64)
            new = {"password": bcrypt_sha256.hash(form.password1.data),
                   "login_token": login_token,
                   "reset_datetime": None}
            old = {"id": user_id, "reset_datetime": not(None)}
            logic.crud(users, new, old, conn)
            return redirect(url_for(".login", login_token=login_token))
            
    submit = ("Save",  url_for(".set_password", token=token))
    return render_page("login.html", form=form, submit=submit)



def send_setpassword_email(email, conn):
    reset_datetime = str(utcnow())
    sql = users.update(). \
            where(users.c.email == email). \
            values(reset_datetime=reset_datetime)
    if conn.execute(sql).rowcount:
        config = current_app.config
        serializer = URLSafeTimedSerializer(config['SECRET_KEY'],
                                            salt="set_password")
        token = serializer.dumps([email, reset_datetime])
        path = url_for("auth.set_password", token=token)
        host = dict(request.headers)["Host"]
        link = "http://{}{}".format(host, path)
        name = config.get("NAME", "<APP>")
        body = _("Please follow {} to reset your {} password. This link can only be used once and will expire in 7 days.").format(link, name)
        subject = _("{} Password Link").format(name)
        sendmail(email, subject, body)



@app.route("/qrcode/<string:email>/<string:secret>")
@login_required(history=False)
def qrcode(email, secret):
    
    service = quote(current_app.config.get("NAME", "<APP>"))
    email = quote(email)
    secret = quote(secret)
    
    # https://github.com/google/google-authenticator/wiki/Key-Uri-Format
    uri = f"otpauth://totp/{service}:{email}?secret={secret}&issuer={service}"
    
    qrcode = pyqrcode.create(uri)
    stream = BytesIO()
    qrcode.svg(stream, scale=5)
    return stream.getvalue(), 200, {
        "Content-Type": "image/svg+xml",
        "Cache-Control": "no-cache, no-store, must-revalidate",
        "Pragma": "no-cache",
        "Expires": "0"}



@app.route("/twofactor", methods=["GET", "POST"])
@login_required()
def twofactor():
    with engine.begin() as conn:
        form = TwoFactorForm(request.form)
        if request.method == "POST" and form.validate():
            sql = users.update(). \
                    where(users.c.id == session["id"]). \
                    values(totp_secret=form.secret.data)
            conn.execute(sql)
            return redirect(url_back())
        
        sql = select([users.c.email]).where(users.c.id == session["id"])
        email = conn.execute(sql).scalar()
        
    secret = base64.b32encode(os.urandom(10)).decode("utf-8")
    qrcode_url = url_for(".qrcode", email=email, secret=secret)
    form.secret.data = secret
            
    buttons = {"submit": (_("Save"), url_for(".twofactor")),
               "back": (_("Cancel"), url_back())}
    title = _("Please scan QR code with the Google Authenticator App on your smartphone.")
    return render_page("twofactor.html", form=form, buttons=buttons, qrcode_url=qrcode_url, title=title)



