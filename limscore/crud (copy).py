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



__all__ = ("app", "define_listview", "crud_route", "update_view")



app = Blueprint("crud", __name__, url_prefix="/tables")


crudlists_by_group = defaultdict(dict)



class MemoryDict(OrderedDict):
    def __missing__(self, key):
        self[key] = ""
        return ""
    


@app.route("/")
@login_required()
def tables_list():
    rows = []
    for table, endpoint in sorted(crudlists_by_group.get(session["group"], {}).items()):
        rows += [tablerow((table.title(), ()), **{"class": "clickable", "data": [("href", url_fwrd(endpoint))]})]
    return render_template("table.html", table={"rows": rows}, title="Table", navbar=navbar("Tables"))



def make_join(primary_table, foreign_table, reverse=False):
    for column in primary_table.c:
        if column.foreign_keys:
            foreign_column = tuple(column.foreign_keys)[0].column
            if foreign_column.table == foreign_table:
                return (foreign_table if not reverse else primary_table, column == foreign_column)



def make_joins(tables):
    if len(tables) == 1:
        return tables[0]
    primary_table = tables[0]
    m2m_tables = []
    joinplans = []
    for foreign_table in tables[1:]:
        joinplan = make_join(primary_table, foreign_table) or make_join(foreign_table, primary_table, reverse=True)
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



def define_listview(fields, headings, formclass=None, register=True, groups=(), sql=None, **kwargs):
    memory = MemoryDict()
    for column in fields:
        if hasattr(column, "__call__"):
            column(memory)
        else:
            memory[column]
    columns = list(memory.keys())
    tables = list(OrderedDict((column.table, None) for column in columns).keys())
    primary_table = tables[0]

    update_endpoint = "crud.{}_update".format(primary_table.name)
    insert_endpoint = "crud.{}_insert".format(primary_table.name)
    reorder_endpoint = "crud.{}_reorder".format(primary_table.name)
    list_endpoint = "crud.{}_list".format(primary_table.name)


    @login_required(*groups)
    def list_function():
        nonlocal sql
        
        extra_columns = [primary_table.c.id]
        if "deleted" in primary_table.c:
            extra_columns += [primary_table.c.deleted]
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
                
        if sql is None:
            sql = select(columns + extra_columns).select_from(primary_table if len(tables) == 1 else make_joins(tables)).order_by(*order)

        def kwargs(row):
            return {"class": "clickable", "data": [("href", url_fwrd(update_endpoint, row_id=row["id"]))]} if update_endpoint in current_app.view_functions else {}
        
        rows = OrderedDict()
        with engine.connect() as conn:
            for row in conn.execute(sql):
                output = [[row[column] if not hasattr(column, "__call__") else column(row), ()] for column in fields]
                if row["id"] in rows:
                    previous = rows[row["id"]][0]
                    for index, cell in enumerate(output):
                        if previous[index][0] != cell[0]:
                            previous[index][0] += ", {}".format(cell[0])
                else:
                    rows[row["id"]] = tablerow(*output, deleted=(row["deleted"] if "deleted" in row else False), **kwargs(row))
                                
        table =  {"headings": [(heading, ()) for heading in headings], "rows": rows.values()}
        if insert_endpoint in current_app.view_functions:
            table["toolbar"] = (("", {"icon": "plus", "href": url_fwrd(insert_endpoint)}),)
                
        buttons = [("Back", {"href": url_back()})]
        if reorder_endpoint in current_app.view_functions:
            buttons += [("Reorder", {"href": url_fwrd(reorder_endpoint), "class": "float-right"})]
        return render_template("table.html", title=primary_table.name.title(), table=table, buttons=buttons, navbar=navbar("Tables"))


    @login_required(*groups)
    def reorder_function():
        columns = [primary_table.c.name]
        #if "name" in primary_table.c:
            #columns += []
        #elif "surname" in primary_table.c and "forename" in primary_table.c:
            #columns += [primary_table.c.surname, primary_table.c.forename]
        sql = select(columns)
        if "deleted" in primary_table.c:
            sql = sql.where(primary_table.c.deleted == False)
        sql = sql.order_by(primary_table.c.order)

        with engine.begin() as conn:
            items = [row[0] for row in conn.execute(sql)]
            form = ReorderForm(request.form)
            
            if request.method == "POST" and form.validate():
                for index, name in enumerate(form.order.data.split(",")[:-1]):
                    logic.admin_update(primary_table, where=(primary_table.c.name == name), values={"order": index}, conn=conn)
                return redirect(url_back())
                
        buttons = [("Save", {"submit": url_for(reorder_endpoint)}), ("Back", {"href": url_back()})]
        return  render_template("reorder.html", title="Reorder {}".format(primary_table.name.title()), items=items, form=form, buttons=buttons, navbar=navbar("Tables"))


    app.add_url_rule("/{}".format(primary_table.name), endpoint=list_endpoint[5:], view_func=list_function, methods=["GET"])
    if "order" in primary_table.c:
        app.add_url_rule("/{}/reorder".format(primary_table.name), endpoint=reorder_endpoint[5:], view_func=reorder_function, methods=["GET", "POST"])
    if groups and register:
        crudlists_by_group[groups[0]][primary_table.name.title()] = list_endpoint
    if formclass is not None:
        define_editview(primary_table, formclass, groups=groups, **kwargs)



def list_view(fields, headings):
    memory = MemoryDict()
    for column in fields:
        if hasattr(column, "__call__"):
            column(memory)
        else:
            memory[column]
    columns = list(memory.keys())
    tables = list(OrderedDict((column.table, None) for column in columns).keys())
    primary_table = tables[0]

    update_endpoint = "crud.{}_update".format(primary_table.name)
    insert_endpoint = "crud.{}_insert".format(primary_table.name)
    reorder_endpoint = "crud.{}_reorder".format(primary_table.name)

    extra_columns = [primary_table.c.id]
    if "deleted" in primary_table.c:
        extra_columns += [primary_table.c.deleted]
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
            
    def kwargs(row):
        return {"class": "clickable", "data": [("href", url_fwrd(update_endpoint, row_id=row["id"]))]} if update_endpoint in current_app.view_functions else {}
    
    rows = OrderedDict()
    with engine.connect() as conn:
        sql = select(columns + extra_columns).select_from(make_joins(tables)).order_by(*order)
        for row in conn.execute(sql):
            output = [[row[column] if not hasattr(column, "__call__") else column(row), ()] for column in fields]
            if row["id"] in rows:
                previous = rows[row["id"]][0]
                for index, cell in enumerate(output):
                    if previous[index][0] != cell[0]:
                        previous[index][0] += ", {}".format(cell[0])
            else:
                rows[row["id"]] = tablerow(*output, deleted=(row["deleted"] if "deleted" in row else False), **kwargs(row))
                            
    table =  {"headings": [(heading, ()) for heading in headings], "rows": rows.values()}
    if insert_endpoint in current_app.view_functions:
        table["toolbar"] = (("", {"icon": "plus", "href": url_fwrd(insert_endpoint)}),)
            
    buttons = [("Back", {"href": url_back()})]
    if reorder_endpoint in current_app.view_functions:
        buttons += [("Reorder", {"href": url_fwrd(reorder_endpoint), "class": "float-right"})]
    return render_template("table.html", title=primary_table.name.title(), table=table, buttons=buttons, navbar=navbar("Tables"))



def list_route(table):
    """ Decorator to provide routing for a crud update/insert view as a shorthand for app.route.
        Delete is offered within the update view if the table cintains a deleted column.

    Args:
        table (str): Name of table to be updated.
        new (bool): If True (default) then inserts are allowed.
        
    Raises:
        Never raises an exception.
        
     """
    def decorator(function):
        app.add_url_rule("/{}".format(table), endpoint="{}_list".format(table), view_func=function, methods=["GET"])
        if insert:
            app.add_url_rule("/{}/new".format(table), endpoint="{}_insert".format(table), view_func=function, methods=["GET", "POST"])
        return function
    
    return decorator



    @login_required(*groups)
    def reorder_function():
        columns = [primary_table.c.name]
        #if "name" in primary_table.c:
            #columns += []
        #elif "surname" in primary_table.c and "forename" in primary_table.c:
            #columns += [primary_table.c.surname, primary_table.c.forename]
        sql = select(columns)
        if "deleted" in primary_table.c:
            sql = sql.where(primary_table.c.deleted == False)
        sql = sql.order_by(primary_table.c.order)

        with engine.begin() as conn:
            items = [row[0] for row in conn.execute(sql)]
            form = ReorderForm(request.form)
            
            if request.method == "POST" and form.validate():
                for index, name in enumerate(form.order.data.split(",")[:-1]):
                    logic.admin_update(primary_table, where=(primary_table.c.name == name), values={"order": index}, conn=conn)
                return redirect(url_back())
                
        buttons = [("Save", {"submit": url_for(reorder_endpoint)}), ("Back", {"href": url_back()})]
        return  render_template("reorder.html", title="Reorder {}".format(primary_table.name.title()), items=items, form=form, buttons=buttons, navbar=navbar("Tables"))


    if "order" in primary_table.c:
        app.add_url_rule("/{}/reorder".format(primary_table.name), endpoint=reorder_endpoint[5:], view_func=reorder_function, methods=["GET", "POST"])
    if groups and register:
        crudlists_by_group[groups[0]][primary_table.name.title()] = list_endpoint



#def define_editview(primary_table, FormClass, groups=(), insert=True, edit_function=None, delete_function=None):
        
    #update_endpoint = "crud.{}_update".format(primary_table.name)
    #insert_endpoint = "crud.{}_insert".format(primary_table.name)
    #delete_endpoint = "crud.{}_delete".format(primary_table.name)


    #if edit_function is None:
        #@login_required(*groups)
        #def edit_function(row_id=None):
            #with engine.begin() as conn:
                #columns = [getattr(primary_table.c, name) for name in FormClass().keys() if name in primary_table.c]
                #if "deleted" in primary_table.c:
                    #columns += [primary_table.c.deleted]
                #if row_id is not None:
                    #old_data = dict(conn.execute(select(columns).where(primary_table.c.id == row_id)).first() or abort(BadRequest))
                    #if old_data.get("deleted", False):
                        #return redirect(url_fwrd(delete_endpoint, row_id=row_id, action="restore"))
                #else:
                    #old_data = {}
                
                #form = FormClass()
                #linking_tables = {}
                
                #for name, field in form.items():
                    #if hasattr(field, "choices"):
                        #if name in primary_table.c:
                            #column = primary_table.c[name]
                            #foreign_table = tuple(column.foreign_keys)[0].column.table
                            #if "deleted" in foreign_table.c:
                                #where_clause = foreign_table.c.deleted == False
                                #if old_data:
                                    #where_clause = or_(where_clause, foreign_table.c.id == old_data[name])
                            #else:
                                #where_clause = None
                                
                            #if "name" in foreign_table.c:
                                #sql = select([foreign_table.c.id, foreign_table.c.name]).order_by(foreign_table.c.name)
                            #elif "surname" in foreign_table.c and "forename" in foreign_table.c:
                                #sql = select([foreign_table.c.id, foreign_table.c.surname, foreign_table.c.forename]).order_by(foreign_table.c.surname, foreign_table.c.forename)                        
                            #if where_clause is not None:
                                #sql = sql.where(where_clause)
                            #rows = [dict(row) for row in conn.execute(sql)]
                            
                        #else:
                            #for linking_table in primary_table.metadata.sorted_tables:
                                #if name in linking_table.c:
                                    #joinplan = make_join(linking_table, primary_table)
                                    #if joinplan:
                                        #primary_column = joinplan[1].left # column in linking table that joins to primary table
                                        #linking_column = linking_table.c[name] # column in linking table that joins to foreign table
                                        #foreign_column = tuple(linking_column.foreign_keys)[0].column # column in foreign table that joins to linking_table
                                        #foreign_table = foreign_column.table
                                        
                                        #if "name" in foreign_table.c:
                                            #sql = select([foreign_table.c.id, foreign_table.c.name, linking_column.label("present")]). \
                                                    #order_by(foreign_table.c.name)
                                        #elif "surname" in foreign_table.c and "forename" in foreign_table.c:
                                            #sql = select([foreign_table.c.id, foreign_table.c.surname, foreign_table.c.forename, linking_column.label("present")]). \
                                                    #order_by(foreign_table.c.surname, foreign_table.c.forename)

                                        #if "deleted" in foreign_table.c:
                                            #where_clause = foreign_table.c.deleted == False
                                            #if old_data:
                                                #where_clause = or_(where_clause, linking_column != None)
                                        #else:
                                            #where_clause = None
                                            
                                        #sql = sql.select_from(join(foreign_table, linking_table, and_(linking_column == foreign_column, primary_column == row_id), isouter=True))
                                        #if where_clause is not None:
                                            #sql = sql.where(where_clause)
                                            
                                        #rows = [dict(row) for row in conn.execute(sql)]
                                        #old_data[name] = [row["id"] for row in rows if row.pop("present")]
                                        #linking_tables[name] = {"table": linking_table, "primary_column": primary_column, "linking_column": linking_column}
                                        #break
                                
                        #if rows:
                            #if "name" in rows[0]:
                                #field.choices = [(row["id"], row["name"]) for row in rows]
                            #else:
                                #field.choices = [(row["id"], surname_forename(row["surname"], row["forename"])) for row in rows]                            
                
                #form.fill(request.form if request.method == "POST" else old_data)
                #if request.method == "POST" and form.validate():
                    #form_data = form.data
                    #for name, linking_table in linking_tables.items():
                        #linking_table["new_data"] = form_data.pop(name)
                        #linking_table["old_data"] = old_data.get(name)
                    
                    #try:
                        #if row_id is None:
                            #row_id = logic.admin_insert(primary_table, values=form_data, conn=conn).inserted_primary_key[0]
                        #else:
                            #logic.admin_update(primary_table, where=(primary_table.c.id == row_id), values=form_data, conn=conn)

                        #for linking_table in linking_tables.values():
                            #logic.m2m(conn=conn, row_id=row_id, **linking_table)
                        #return redirect(url_back())

                    #except IntegrityError as e:
                        #try:
                            #name = e._message().split(" UNIQUE constraint failed: ")[1].split(".")[1]
                            #getattr(form, name).errors = "{} must be unique.".format(name.title())
                        #except (IndexError, AttributeError):
                            #raise e
                    
            #title = "{} {}".format("Edit" if row_id is not None else "New", primary_table.name.title())
            #buttons=[("Save", {"submit": url_for(request.endpoint, **request.view_args)}), ("Cancel", {"href": url_back()})]
            #if row_id is not None and delete_endpoint in current_app.view_functions:
                #buttons += [("Delete", {"href": url_fwrd(delete_endpoint, row_id=row_id, action="delete"), "class": "float-right", "style": "danger"})]
            #return render_template("form.html", form=form, buttons=buttons, title=title, navbar=navbar("Tables"))


    #if delete_function is None:
        #@login_required(*groups)
        #def delete_function(row_id, action):
            #with engine.begin() as conn:
                #old_data = dict(conn.execute(select(primary_table.c).where(and_(primary_table.c.id == row_id, primary_table.c.deleted == (action == "restore")))).first() or ())
                #if not old_data: # action we are trying to perform has already been carried out
                    #return url_back()

                #if request.method == "POST":
                    #logic.admin_update(primary_table, where=(primary_table.c.id == row_id), values={"deleted": bool(action == "delete")}, conn=conn)
                    #return redirect(url_back(-2))

                #else:
                    #name = old_data["name"] if "name" in old_data else "{} {}".format(old_data["forename"], old_data["surname"])
                    #message = ["Are you sure you want to {} {}?".format(action, name)]
                    #buttons = (("Yes", {"submit": url_for(delete_endpoint, row_id=row_id, action=action)}), ("No", {"href": url_back(-1 if action == "delete" else -2)}))            
                    
            #return render_template("modal.html", message=message, buttons=buttons, navbar=navbar("Tables"))


    #app.add_url_rule("/{}/<int:row_id>".format(primary_table.name), endpoint=update_endpoint[5:], view_func=edit_function, methods=["GET", "POST"])
    #if insert:
        #app.add_url_rule("/{}/new".format(primary_table.name), endpoint=insert_endpoint[5:], view_func=edit_function, methods=["GET", "POST"])
    #if "deleted" in primary_table.c:
        #app.add_url_rule("/{}/<int:row_id>/<any(delete, restore):action>".format(primary_table.name), endpoint=delete_endpoint[5:], view_func=delete_function, methods=["GET", "POST"])












def update_view(primary_table, FormClass, row_id=None):
    with engine.begin() as conn:
        columns = [getattr(primary_table.c, name) for name in FormClass().keys() if name in primary_table.c]
        if "deleted" in primary_table.c:
            columns += [primary_table.c.deleted]
        old_data = dict(conn.execute(select(columns).where(primary_table.c.id == row_id)).first() or abort(BadRequest)) if row_id is not None else {}
        form = FormClass()
        
        linking_tables = {}
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
                                linking_tables[name] = {"table": linking_table, "primary_column": primary_column, "linking_column": linking_column}
                                break
                        
                if rows:
                    if "name" in rows[0]:
                        field.choices = [(row["id"], row["name"]) for row in rows]
                    else:
                        field.choices = [(row["id"], surname_forename(row["surname"], row["forename"])) for row in rows]                            
        
        form.fill(request.form if request.method == "POST" else old_data)
        if request.method == "POST" and form.validate():
            form_data = form.data
            action = request.args.get("action", "") if "deleted" in primary_table.c else ""
            if action == "delete":
                form_data["deleted"] = True
            elif action == "restore":
                form_data["deleted"] = False

            for name, linking_table in linking_tables.items():
                linking_table["new_data"] = form_data.pop(name)
                linking_table["old_data"] = old_data.get(name)
            
            try:
                if row_id is None:
                    row_id = logic.admin_insert(primary_table, values=form_data, conn=conn).inserted_primary_key[0]
                else:
                    logic.admin_update(primary_table, where=(primary_table.c.id == row_id), values=form_data, conn=conn)

                for linking_table in linking_tables.values():
                    logic.m2m(conn=conn, row_id=row_id, **linking_table)
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



def crud_route(function):
    """ Decorator to provide routing for crud update/insert/delete/list/reorder
        views instead of app.route. The function name must be of the format 
        databasetable_crudoperation where databasetable is the name of the 
        database table to be operated upon although it is just used in the
        function name and does not have to be a real table. crudoperation must
        be one of update, list or reorder. Delete and is automatically offered 
        within the update view if the table contains a deleted column. An 
        insert view is automatically offered with an update view if the update
        function has a default row_id of None.

    Args:
        function (callable): The view function.
        
    Raises:
        Never raises an exception.
        
     """
     
    tablename, action = function.__name__.split("_") 
    if action == "update":
        app.add_url_rule("/{}/<int:row_id>".format(tablename),
                         endpoint=function.__name__,
                         view_func=function,
                         methods=["GET", "POST"])
        if list(signature(function).parameters)[0].default is None:
            app.add_url_rule("/{}/new".format(tablename),
                             endpoint="{}_insert".format(tablename),
                             view_func=function,
                             methods=["GET", "POST"])
    
    elif action == "":
            
            
            
            
            
            
    return function
    
    
    
    
    
    
    
    
    
    
