import pdb
from collections import OrderedDict, defaultdict
from inspect import signature

from sqlalchemy import select, join, or_, and_
from sqlalchemy.exc import IntegrityError


from flask import render_template, redirect, url_for, request, Blueprint, current_app, session
from werkzeug.exceptions import Conflict, Forbidden, BadRequest

from .utils import url_fwrd, url_back, tablerow, navbar, abort, engine, login_required, surname_forename
from .forms import ReorderForm
from . import logic
from .models import metadata


__all__ = ("list_view", "reorder_view", "upsert_view", "crud_route", "app")



app = Blueprint("admin", __name__)


crudlists_by_group = defaultdict(dict)
    


@app.route("/")
@login_required()
def tables_list():
    rows = []
    for table, endpoint in sorted(crudlists_by_group.get(session["group"], {}).items()):
        rows += [tablerow((table.title(), ()), **{"class": "clickable", "data": [("href", url_fwrd(endpoint))]})]
    return render_template("table.html",
                           table={"rows": rows},
                           title="Table",
                           navbar=navbar("Tables"))



def crud_route(*groups):
    """Decorator to provide routing for crud functions. These functions
        must be named tablename_action where action is upsert or list.

    Args:
        groups (list of str): Groups allowed to make a request to this 
            endpoint.
        
    Returns:
        decorated function.
        
    Raises:
        RuntimeError if name of decorated function is of the wrong format.
        
     """
    def decorator(function):
        nonlocal groups
        if not groups:
            groups = ["Admin.Administrator", "Admin."]
        
        tablename, action = function.__name__.split("_")
        if action == "upsert":
            app.add_url_rule("/{}/<int:row_id>".format(tablename),
                             endpoint=function.__name__,
                             view_func=function,
                             methods=["GET", "POST"])
            if list(signature(function).parameters.items())[0][1].default is None:
                app.add_url_rule("/{}/new".format(tablename),
                                 endpoint=function.__name__,
                                 view_func=function,
                                 methods=["GET", "POST"])            

        elif action == "list":
            app.add_url_rule("/{}".format(tablename),
                             endpoint=function.__name__,
                             view_func=function, methods=["GET"])
            for group in groups:
                if not group.endswith("."):
                    endpoint = ".{}".format(function.__name__)
                    crudlists_by_group[group][tablename] = endpoint

            if tablename in metadata.tables:
                table = metadata.tables[tablename]
                if "order" in table.c:
                    @login_required(*groups)
                    def reorder_function():
                        return reorder_view(table)
                    app.add_url_rule("/{}/reorder".format(tablename),
                                    endpoint="{}_reorder".format(tablename),
                                    view_func=reorder_function,
                                    methods=["GET", "POST"])
            
        else:
            msg = "Invalid crud function name {}".format(function.__name__)
            raise RuntimeError(msg)
                
        return function
    return decorator



class MemoryDict(OrderedDict):
    def __missing__(self, key):
        self[key] = ""
        return ""



def make_join(primary_table, foreign_table, reverse=False):
    for column in primary_table.c:
        if column.foreign_keys:
            foreign_column = tuple(column.foreign_keys)[0].column
            if foreign_column.table == foreign_table:
                table = foreign_table if not reverse else primary_table
                return (table, column == foreign_column)



def make_joins(tables):
    if len(tables) == 1:
        return tables[0]
    primary_table = tables[0]
    m2m_tables = []
    joinplans = []
    for foreign_table in tables[1:]:
        joinplan = make_join(primary_table, foreign_table) or \
                   make_join(foreign_table, primary_table, reverse=True)
        if joinplan:
            joinplans += [joinplan]
        else:
            m2m_tables += [foreign_table]

    for foreign_table in m2m_tables:
        for linking_table in primary_table.metadata.sorted_tables:
            if linking_table not in tables:
                joinplan = [make_join(linking_table, primary_table, reverse=True), make_join(linking_table, foreign_table)]
                if None not in joinplan:
                    joinplans += joinplan
                    break
    selectable = join(primary_table, *joinplans[0], isouter=True)
    for joinplan in joinplans[1:]:
        selectable = selectable.join(*joinplan, isouter=True)
    return selectable                



def list_view(*table_definition):#, **filters):
    headings, fields = zip(*table_definition)
    
    memory = MemoryDict()
    for column in fields:
        if hasattr(column, "__call__"):
            column(memory)
        else:
            memory[column]
    columns = list(memory.keys())
    tables = list(OrderedDict((column.table, None) for column
                              in columns).keys())
    primary_table = tables[0]
    columns += [primary_table.c.id]

    upsert_endpoint = "admin.{}_upsert".format(primary_table.name)
    reorder_endpoint = "admin.{}_reorder".format(primary_table.name)

    if "deleted" in primary_table.c:
        columns += [primary_table.c.deleted]
        order = [primary_table.c.deleted]
    else:
        order = []

    for table in tables:
        if "order" in table.c:
            order += [table.c.order]
        elif "name" in table.c:
            order += [table.c.name]
        elif "surname" in table.c and "forename" in table.c:
            order += [table.c.surname, table.c.forename]
    
    sql = select(columns).select_from(make_joins(tables)).order_by(*order)
    #if filters:
        #where_clauses = [getattr(primary_table.c, key) == val for key, val
                         #in filters.items()]
        #sql = sql.where(*where_clauses)
    
    if upsert_endpoint in current_app.view_functions:
        def kwargs(row):
            return {"class": "clickable",
                    "data": [("href", url_fwrd(upsert_endpoint,
                                               row_id=row["id"]))]}
    else:
        def kwargs(row):
            return {}
    
    rows = OrderedDict()
    with engine.connect() as conn:
        for row in conn.execute(sql):
            output = [[row[column] if not hasattr(column, "__call__") else column(row), ()] for column in fields]
            if row["id"] in rows:
                previous = rows[row["id"]][0]
                for index, cell in enumerate(output):
                    try:
                        if cell[0] not in previous[index][0]:
                            previous[index][0] += ", {}".format(cell[0])
                    except TypeError: # previous may not be a string and not have a __contains__ method
                        pass
            else:
                rows[row["id"]] = tablerow(*output, deleted=(row["deleted"] if "deleted" in row else False), **kwargs(row))
                            
    table =  {"headings": [(heading, ()) for heading in headings], "rows": rows.values()}
    if upsert_endpoint in current_app.view_functions:
        function = current_app.view_functions[upsert_endpoint]
        if list(signature(function).parameters.items())[0][1].default is None:
            table["toolbar"] = (("", {"icon": "plus", "href": url_fwrd(upsert_endpoint)}),)
            
    buttons = [("Back", {"href": url_back()})]
    if reorder_endpoint in current_app.view_functions:
        buttons += [("Reorder", {"href": url_fwrd(reorder_endpoint), "class": "float-right"})]
    return render_template("table.html", title=primary_table.name.title(), table=table, buttons=buttons, navbar=navbar("Tables"))



def reorder_view(primary_table):
    columns = [primary_table.c.name]
    sql = select(columns)
    if "deleted" in primary_table.c:
        sql = sql.where(primary_table.c.deleted == False)
    sql = sql.order_by(primary_table.c.order)

    with engine.begin() as conn:
        items = [row[0] for row in conn.execute(sql)]
        form = ReorderForm(request.form)
        
        if request.method == "POST" and form.validate():
            for index, name in enumerate(form.order.data.split(",")[:-1]):
                logic.admin_update(primary_table,
                                   where=(primary_table.c.name == name),
                                   values={"order": index},
                                   conn=conn)
            return redirect(url_back())
                
    buttons = [("Save", {"submit": url_for(request.endpoint)}),
               ("Back", {"href": url_back()})]
    title = "Reorder {}".format(primary_table.name.title())
    return  render_template("reorder.html",
                            title=title,
                            items=items,
                            form=form,
                            buttons=buttons,
                            navbar=navbar("Tables"))



def upsert_view(row_id, primary_table, FormClass):
    with engine.begin() as conn:
        columns = [getattr(primary_table.c, name) for name in FormClass().keys() if name in primary_table.c]
        if "deleted" in primary_table.c:
            columns += [primary_table.c.deleted]
        old_data = dict(conn.execute(select(columns).where(primary_table.c.id == row_id)).first() or abort(BadRequest)) if row_id is not None else {}
        form = FormClass()
        
        m2m_links = []
        for name, field in form.items():
            if hasattr(field, "choices"):
                if name in primary_table.c:
                    column = primary_table.c[name]
                    foreign_table = tuple(column.foreign_keys)[0].column.table
                    if "deleted" in foreign_table.c:
                        where_clause = foreign_table.c.deleted == False
                        if old_data:
                            where_clause = or_(where_clause, foreign_table.c.id == old_data[name])
                    else:
                        where_clause = None
                        
                    if "name" in foreign_table.c:
                        sql = select([foreign_table.c.id, foreign_table.c.name]).order_by(foreign_table.c.name)
                    elif "surname" in foreign_table.c and "forename" in foreign_table.c:
                        sql = select([foreign_table.c.id, foreign_table.c.surname, foreign_table.c.forename]).order_by(foreign_table.c.surname, foreign_table.c.forename)                        
                    if where_clause is not None:
                        sql = sql.where(where_clause)
                    rows = [dict(row) for row in conn.execute(sql)]
                    
                else:
                    for linking_table in primary_table.metadata.sorted_tables:
                        if name in linking_table.c:
                            joinplan = make_join(linking_table, primary_table)
                            if joinplan:
                                primary_column = joinplan[1].left # column in linking table that joins to primary table
                                linking_column = linking_table.c[name] # column in linking table that joins to foreign table
                                foreign_column = tuple(linking_column.foreign_keys)[0].column # column in foreign table that joins to linking_table
                                foreign_table = foreign_column.table
                                
                                if "name" in foreign_table.c:
                                    sql = select([foreign_table.c.id, foreign_table.c.name, linking_column.label("present")]). \
                                            order_by(foreign_table.c.name)
                                elif "surname" in foreign_table.c and "forename" in foreign_table.c:
                                    sql = select([foreign_table.c.id, foreign_table.c.surname, foreign_table.c.forename, linking_column.label("present")]). \
                                            order_by(foreign_table.c.surname, foreign_table.c.forename)

                                if "deleted" in foreign_table.c:
                                    where_clause = foreign_table.c.deleted == False
                                    if old_data:
                                        where_clause = or_(where_clause, linking_column != None)
                                else:
                                    where_clause = None
                                    
                                sql = sql.select_from(join(foreign_table, linking_table, and_(linking_column == foreign_column, primary_column == row_id), isouter=True))
                                if where_clause is not None:
                                    sql = sql.where(where_clause)
                                
                                rows = [dict(row) for row in conn.execute(sql)]
                                old_data[name] = [row["id"] for row in rows if row.pop("present")]
                                m2m_links += [{"table": linking_table,
                                               "field": name,
                                               "primary_column": primary_column,
                                               "linking_column": linking_column,
                                               "primary_id": row_id}]
                                break
                        
                if rows:
                    if "name" in rows[0]:
                        field.choices = [(row["id"], row["name"]) for row in rows]
                    else:
                        field.choices = [(row["id"], surname_forename(row)) for row in rows]                            
        
        form.fill(request.form if request.method == "POST" else old_data)
        if request.method == "POST" and form.validate():
            form_data = form.data
            action = request.args.get("action", "") if "deleted" in primary_table.c else ""
            if action == "delete":
                form_data["deleted"] = True
            elif action == "restore":
                form_data["deleted"] = False

            for m2m_link in m2m_links:
                m2m_link["new_linking_ids"] = form_data.pop(m2m_link["field"])
                m2m_link["old_linking_ids"] = old_data.pop(m2m_link.pop("field"))
            
            try:
                if row_id is None:
                    pdb.set_trace()
                    row_id = logic.admin_insert(primary_table, values=form_data, conn=conn).inserted_primary_key[0]
                else:
                    logic.admin_update(primary_table, where=(primary_table.c.id == row_id), values=form_data, conn=conn)

                for m2m_link in m2m_links:
                    logic.m2m(conn=conn, **m2m_link)
                return redirect(url_back())

            except IntegrityError as e:
                try:
                    name = e._message().split(" UNIQUE constraint failed: ")[1].split(".")[1]
                    getattr(form, name).errors = "{} must be unique.".format(name.title())
                except (IndexError, AttributeError):
                    raise e
            
    title = "{} {}".format("Edit" if row_id is not None else "New", primary_table.name.title())
    buttons=[("Save", {"submit": url_for(request.endpoint, row_id=row_id)}), ("Cancel", {"href": url_back()})]
    if row_id is not None and "deleted" in primary_table.c:
        if not old_data["deleted"]:
            buttons += [("Delete", {"submit": url_for(request.endpoint, row_id=row_id, action="delete"), "class": "float-right", "style": "danger"})]
        else:
            buttons += [("Restore", {"submit": url_fwrd(request.endpoint, row_id=row_id, action="restore"), "class": "float-right", "style": "danger"})]
    return render_template("form.html", form=form, buttons=buttons, title=title, navbar=navbar("Tables"))



