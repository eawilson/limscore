import pdb
from html import escape

from sqlalchemy import (select,
                        join,
                        or_,
                        and_)
from sqlalchemy.exc import IntegrityError

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
from jinja2 import Markup

from passlib.hash import bcrypt_sha256

from .models import (editlogs,
                     users,
                     groups,
                     sites,
                     projects,
                     users_sites,
                     users_projects,
                     users_groups)
from .forms import UserForm
from .utils import (render_page,
                    tablerow,
                    initial_surname,
                    surname_forename,
                    store_history,
                    url_fwrd,
                    url_back,
                    engine, navbar,
                    login_required,
                    valid_groups,
                    abort,
                    unique_violation_or_reraise)
from .wrappers import Local
from .logic import admin_edit, edit_m2m
from .crud import list_view
from .auth import send_setpassword_email



app = Blueprint("admin", __name__)



@app.route("/audit/<string:tablename>/<int:row_id>")
@login_required("Admin.Administrator", "Admin.")
def editlog(tablename, row_id):
    with engine.connect() as conn:
        sql = select([users.c.forename,
                      users.c.surname,
                      editlogs.c.action,
                      editlogs.c.details,
                      editlogs.c.datetime]). \
                select_from(join(editlogs, users,
                                 editlogs.c.user_id == users.c.id)). \
                where(and_(editlogs.c.tablename == tablename,
                           editlogs.c.row_id == row_id)). \
                order_by(editlogs.c.datetime, editlogs.c.id)
        rows = []
        for row in conn.execute(sql):
            name = initial_surname(row[users.c.forename], row[users.c.surname])
            html = escape(row[editlogs.c.details]).replace("\t", "<br>")
            details = Markup(html)
            rows += [tablerow(row[editlogs.c.action],
                              details,
                              name,
                              Local(row[editlogs.c.datetime]))]
    
    table = {"head": ("Action", "Details", "User", "Date"),
             "body": rows}
    return render_page("table.html",
                       table=table,
                       buttons={"back": ("Back",  url_back())},
                       title="Audit Trail")
        
        

@app.route("/users/new", methods=["GET", "POST"])
@app.route("/users/<int:row_id>", methods=["GET", "POST"])
@login_required("Admin.Administrator", "Admin.")
def users_upsert(row_id=None):
    with engine.begin() as conn:
        if row_id is not None:
            sql = select([users.c.id,
                          users.c.forename,
                          users.c.surname,
                          users.c.username,
                          users.c.email,
                          users.c.restricted,
                          users.c.password,
                          users.c.deleted]). \
                    where(users.c.id == row_id)
            old_data = dict(conn.execute(sql).first() or abort(BadRequest))
        else:
            old_data = {}
        
        
        where = and_(groups.c.id == users_groups.c.group_id,
                      users_groups.c.user_id == row_id)
        sql = select([groups.c.name,
                      groups.c.id,
                      users_groups.c.user_id]). \
                select_from(join(groups, users_groups, where, isouter=True)). \
                where(groups.c.name.in_(valid_groups)). \
                order_by(groups.c.name)
        old_data["group_id"] = []
        group_id_choices = []
        my_group_id = None
        for row in conn.execute(sql):
            group_id_choices += [(row[groups.c.id], row[groups.c.name])]
            if row[users_groups.c.user_id] is not None:
                old_data["group_id"] += [row[groups.c.id]]
                if row[users_groups.c.user_id] == session["id"] and \
                                        row[groups.c.name] == session["group"]:
                    group_id_choices[-1] += ("disabled",)
                    my_group_id = row[groups.c.id]
                    

        where = and_(sites.c.id == users_sites.c.site_id,
                      users_sites.c.user_id == row_id)
        sql = select([sites.c.name,
                      sites.c.id,
                      users_sites.c.user_id]). \
                select_from(join(sites, users_sites, where, isouter=True)). \
                where(sites.c.deleted == False). \
                order_by(sites.c.name)
        old_data["site_id"] = []
        site_id_choices = []
        for row in conn.execute(sql):
            site_id_choices += [(row[sites.c.id], row[sites.c.name])]
            if row[users_sites.c.user_id] is not None:
                old_data["site_id"] += [row[sites.c.id]]
        
        
        where = and_(projects.c.id == users_projects.c.project_id,
                      users_projects.c.user_id == row_id)
        sql = select([projects.c.name,
                      projects.c.id,
                      users_projects.c.user_id]). \
                select_from(join(projects, users_projects, where, isouter=True)). \
                where(projects.c.deleted == False). \
                order_by(projects.c.name)
        old_data["project_id"] = []
        project_id_choices = []
        for row in conn.execute(sql):
            project_id_choices += [(row[projects.c.id], row[projects.c.name])]
            if row[users_projects.c.user_id] is not None:
                old_data["project_id"] += [row[projects.c.id]]
        
        form = UserForm(request.form if request.method=="POST" else old_data)
        form.group_id.choices = group_id_choices
        form.site_id.choices = site_id_choices
        form.project_id.choices = project_id_choices
        if current_app.config.get("EMAIL", False):
            del form.password
        else:
            form.email.required = False
            if old_data.get("password", None) is not None:
                form.password.required = False
        
        if my_group_id is not None and my_group_id not in form.group_id.data:
            form.group_id.data += [my_group_id]

        if request.method == "POST" and form.validate():
            new_data = form.data
            password = new_data.pop("password", None)
            if password is not None:
                new_data["password"] = bcrypt_sha256.hash(password)
            
            if row_id == session["id"]:
                action = ""
            else:
                action = request.args.get("action", "")
                if action == "Delete":
                    new_data["deleted"] = True
                elif action == "Restore":
                    new_data["deleted"] = False
            
            try:
                name = initial_surname(new_data["forename"],
                                       new_data["surname"])
                row_id = admin_edit(users,
                                    row_id,
                                    new_data,
                                    old_data,
                                    conn,
                                    calculated_values={"name": name})
            except IntegrityError as e:
                form[unique_violation_or_reraise(e)].errors = "Must be unique."
            else:
                edit_m2m(users,
                         row_id, 
                         users_groups,
                         new_data["group_id"],
                         old_data.get("group_id", []),
                         group_id_choices,
                         conn)
                edit_m2m(users,
                         row_id, 
                         users_sites,
                         new_data["site_id"],
                         old_data.get("site_id", []),
                         site_id_choices,
                         conn)
                edit_m2m(users,
                         row_id, 
                         users_projects,
                         new_data["project_id"],
                         old_data.get("project_id", []),
                         project_id_choices,
                         conn)
                if current_app.config.get("EMAIL", False) and \
                   (row_id is None or action == "Restore"):
                    send_setpassword_email(new_data, conn)                
                return redirect(url_back())
                
    title = "Edit" if row_id is not None else "New"
    buttons={"submit": ("Save", url_for(".users_upsert", row_id=row_id)),
             "back": ("Cancel", url_back())}
    if row_id is not None and row_id != session["id"]:
        button_action = "Restore" if old_data["deleted"] else "Delete"
        url = url_for(".users_upsert", row_id=row_id, action=button_action)
        buttons["danger"] = (button_action, url)
    if row_id is not None:
        url = url_fwrd(".editlog", tablename="users", row_id=row_id)
        buttons["info"] = ("History", url)
    return render_page("form.html", form=form, buttons=buttons, title=title)



@app.route("/groups")
@login_required("Admin.Administrator", "Admin.")
def groups_list():
    return list_view(("Name",groups.c.name))



@app.route("/users")
@login_required("Admin.Administrator", "Admin.")
def users_list():
    def name(row):
        return surname_forename(row[users.c.surname], row[users.c.forename])
    return list_view(("Name", name),
                     ("Username", users.c.username),
                     ("Email", users.c.email),
                     ("Groups", groups.c.name))
