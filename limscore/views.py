import pdb, os
from datetime import datetime, timedelta, date
from itertools import count
from collections import OrderedDict
from io import BytesIO

from sqlalchemy import select, join, or_, outerjoin, and_

from flask import render_template, session, redirect, url_for, request, send_file, Blueprint, current_app
from werkzeug.exceptions import Conflict, Forbidden, BadRequest, NotFound
from werkzeug.datastructures import MultiDict
from jinja2 import Markup

from . import logic
from .models import users, substrates_sampletypes, sampletypes, locations, consultants, tasks_users, tasktypes, taskstatuses, testtypes, exports, \
                    teststatuses, requests, samples, tasks, tests, TASKSTATUSES, tests_users, testcomments, investigations, reports, patients
from .forms import VolumeForm, TaskForm, SearchForm, DateForm
from .utils import url_fwrd, url_back, strftime, surname_forename, initial_surname, request_table, navbar, normalise, tablerow, date2datetime, request_sql, request_row, \
                    report_sql, report_pdf, abort, engine
from .admin import login_required



views = Blueprint("views", __name__)



class CountUnique(set):
    def __repr__(self):
        return "CountUnique({})".format(repr(list(self)))
    
    def __str__(self):
        return str(len(self))



#def one(resultproxy):
    #if resultproxy is None:
        #abort(BADREQUEST)
    #looped = False
    #for row in resultproxy:
        #if looped:
            #abort(BADREQUEST)
        #looped = True
    #return row



@views.route("/tasks")
@login_required(root=True)
def task_list():
    with engine().connect() as conn:
        sql = request_sql(where_clauses=[tasks.c.taskstatus_id == TASKSTATUSES.Incomplete, requests.c.deleted == False], 
                          order_by=[tasktypes.c.section, tasktypes.c.name, patients.c.surname, patients.c.forename], 
                          additional_select_targets=[tasktypes.c.section, tasktypes.c.name, tasks.c.id, tasktypes.c.edit_function])

        tabrows = [[], []]
        choices = "{}|".format(request.args.get("choices", "")).split("|")[:len(tabrows)]
        rows = []
        for row in conn.execute(sql):
            for i, tabs, text in zip(count(), tabrows, (row[tasktypes.c.section], row[tasktypes.c.name])):
                if not choices[i]:
                    choices[i] = text
                if tabs and tabs[-1]["text"] == text:
                    tabs[-1]["badge"].add(row["request_id"])
                else:
                    tabs.append({"text": text, "badge": CountUnique([row["request_id"]]), "class": "active" if (text==choices[i]) else "", \
                                    "href": url_for("views.task_list", choices="|".join(choices[:i] + [text]))})
                if choices[i] != text:
                    break
                if i == 1:
                    rows += request_row(row, link_function=lambda row: url_fwrd(row[tasktypes.c.edit_function], task_id=row[tasks.c.id]))

    table = {"tabs": tabrows, "rows": rows,
             "headings": (("Lab Number", ()), ("Name", ()), ("MRN", ()), ("NHS Number", ()), ("DOB", ()), ("Location", ()), ("Consultant", ()), ("Clinical Details", ()), \
                          ("Date Received", ()))}
    return render_template("table2.html", table=table, navbar=navbar("Tasks"))



@views.route("/ir/<int:location_id>")
@login_required(root=True)
def ir(location_id):
    if location_id not in (1, 3):
        abort(NotFound)

    with engine().connect() as conn:
        sql = request_sql(where_clauses=[tasks.c.taskstatus_id == TASKSTATUSES.Incomplete, requests.c.deleted == False, requests.c.location_id == location_id, \
                            tasks.c.tasktype_id == 13], order_by=[requests.c.datetime_created], 
                            additional_select_targets=[tasktypes.c.section, tasktypes.c.name, tasks.c.id, tasktypes.c.edit_function])

        rows = []
        for row in conn.execute(sql):
            rows += request_row(row, link_function=lambda row: url_fwrd(row[tasktypes.c.edit_function], task_id=row[tasks.c.id]))

    table = {"rows": rows,
             "headings": (("Lab Number", ()), ("Name", ()), ("MRN", ()), ("NHS Number", ()), ("DOB", ()), ("Location", ()), ("Consultant", ()), ("Clinical Details", ()), \
                          ("Date Received", ()))}
    return render_template("table2.html", table=table, navbar=navbar("IR (MK)" if location_id == 3 else "IR (OUH)"))



@views.route("/requests_by_day", defaults={"comparison": "lt", "ordinal": None})
@views.route("/requests_by_day/<any('lt', 'gt'):comparison>/<int:ordinal>")
@login_required(root=True)
def requests_by_day(comparison, ordinal):
    viewdate = date2datetime(date.fromordinal(ordinal) if ordinal is not None else date.today() + timedelta(1))

    if comparison == "lt":
        sql = select([requests.c.datetime_created]).where(requests.c.datetime_created < viewdate).order_by(requests.c.datetime_created.desc())
    else:
        sql = select([requests.c.datetime_created]).where(requests.c.datetime_created >= viewdate + timedelta(1)).order_by(requests.c.datetime_created)
    
    with engine().connect() as conn:
        try:
            viewdate = date2datetime(conn.execute(sql).scalar().date())
        except AttributeError:
            pass
         
        table = request_table([requests.c.datetime_created >= viewdate, requests.c.datetime_created < viewdate + timedelta(1)], conn, single_row=False)
        
    table["toolbar"] = (("", {"icon": "plus", "href": url_fwrd("requesting.create_lookup")}), 
                        ("", {"icon": "triangle-1-w", "href": url_for("views.requests_by_day", ordinal=viewdate.toordinal(), comparison="lt")}),
                        (viewdate.strftime("%d %b %Y"), ()),
                        ("", {"icon": "triangle-1-e", "href": url_for("views.requests_by_day", ordinal=viewdate.toordinal(), comparison="gt")}))
    return render_template("table2.html", table=table, navbar=navbar("Requests"))



@views.route("/search", methods=["GET", "POST"])
@login_required(root=True)
def search():
    with engine().connect() as conn:
        form = SearchForm(formdata=request.form)
        form.testtype_id.choices = [(0, "")] + list(conn.execute(select([testtypes.c.id, testtypes.c.name]).order_by(testtypes.c.name)))
        form.location_id.choices = [(0, "")] + list(conn.execute(select([locations.c.id, locations.c.name]).order_by(locations.c.name)))

        if request.method == "POST" and form.validate():
            return redirect(url_fwrd("views.requests_searched", **request.form.to_dict()))

    return render_template("form2.html", form=form, buttons=(("Search", {"submit": url_for("views.search")}),), navbar=navbar("Search"))



@views.route("/requests")
@login_required()
def requests_searched():
    with engine().connect() as conn:
        form = SearchForm(formdata=MultiDict(request.args.to_dict().items()))
        form.testtype_id.choices = [(0, "")] + list(conn.execute(select([testtypes.c.id, testtypes.c.name]).order_by(testtypes.c.name)))
        form.location_id.choices = [(0, "")] + list(conn.execute(select([locations.c.id, locations.c.name]).order_by(locations.c.name)))
        
        if not form.validate():
            abort(BadRequest)
        
        comparisons = {"surname": lambda val: patients.c.surname.ilike("{}%".format(val)),
                       "forename": lambda val: patients.c.forename.ilike("{}%".format(val)),
                       "nhs_number": lambda val: patients.c.nhs_number.like("{}%".format(val)),
                       "date_of_birth": lambda val: patients.c.date_of_birth == val,
                       "mrn": lambda val: or_(patients.c.mrn.ilike("{}%".format(val)), requests.c.referrers_mrn.ilike("{}%".format(val))),
                       "lab_number": lambda val: requests.c.lab_number.ilike("{}%".format(val)),
                       "location_id": lambda val: requests.c.location_id == val,
                       "earliest_date": lambda val: requests.c.datetime_created >= val,
                       "latest_date": lambda val: requests.c.datetime_created < val + timedelta(1),
                       "testtype_id": lambda val: tests.c.testtype_id == val}
                       
        table = request_table([comparisons[key](val) for key, val in form.data.items()], conn, single_row=False)
                        
        table["buttons"] = (("Back", {"href": url_back()}),)
    return render_template("table2.html", table=table, navbar=navbar("Search"))



def request_tabs(request_id, selected):
    tabs = [{"text": name, "href": url_for(func, request_id=request_id)} for name, func in (("Tasks", "views.request_tasks"), \
                                                                                            ("Tests", "views.request_tests"), \
                                                                                            ("Results", "views.request_reports"), \
                                                                                            ("Exports", "views.request_exports"))]
    for tab in tabs:
        if tab["text"] == selected:
            tab["class"] = "active"
    return [tabs]



@views.route("/requests/<int:request_id>/tasks")
@login_required()
def request_tasks(request_id):
    with engine().connect() as conn:
        try:
            demographics, request_id = request_table([requests.c.id == request_id, requests.c.deleted == False], conn)
        except Conflict:
            return redirect(url_for("requesting.uncancel_request", request_id=request_id))

        sql = select([sampletypes.c.name, samples.c.number]). \
                select_from(join(samples, sampletypes, samples.c.sampletype_id == sampletypes.c.id)). \
                where(samples.c.request_id == request_id). \
                order_by(sampletypes.c.name)
        samples_involved = ", ".join("{} x {}".format(row[sampletypes.c.name], row[samples.c.number]) for row in conn.execute(sql))

        following_tasks = tasks.alias("following_tasks")
        sql = select([tasks.c.id, tasks.c.taskstatus_id, tasks.c.quantity, tasktypes.c.name, tasktypes.c.edit_function, tasktypes.c.undo_function, tasks_users.c.datetime_completed, \
                      users.c.forename, users.c.surname, taskstatuses.c.name, sampletypes.c.volume_based, sampletypes.c.name, following_tasks.c.taskstatus_id, tasks.c.comment, \
                      samples.c.volume, samples.c.cell_count]). \
                select_from(join(tasks, tasktypes, tasks.c.tasktype_id == tasktypes.c.id). \
                            join(taskstatuses, tasks.c.taskstatus_id == taskstatuses.c.id). \
                            outerjoin(tasks_users, tasks_users.c.task_id == tasks.c.id). \
                            outerjoin(users, users.c.id == tasks_users.c.user_id). \
                            outerjoin(samples, samples.c.id == tasks.c.sample_id). \
                            outerjoin(sampletypes, sampletypes.c.id == samples.c.sampletype_id). \
                            outerjoin(following_tasks, tasks.c.id == following_tasks.c.preceeding_task_id)). \
                where(tasks.c.request_id == request_id). \
                order_by(tasks.c.taskstatus_id == TASKSTATUSES.Incomplete, tasks.c.id, tasks.c.datetime_completed)

        rows = []
        last_task_id = None
        for row in conn.execute(sql) or ():
            user = initial_surname(row[users.c.surname], row[users.c.forename])
            if last_task_id == row[tasks.c.id]:
                rows[-1][0][3][0] += " / {}".format(user)
                rows[-1][0][4][0] = strftime(row[tasks_users.c.datetime_completed])
            else:
                edit_url = {"href": url_fwrd(row[tasktypes.c.edit_function], task_id=row[tasks.c.id])}
                if row[tasktypes.c.edit_function] == "requesting.edit_request":
                    link = ("Edit", edit_url)
                else:
                    if row[tasks.c.taskstatus_id] != TASKSTATUSES.Incomplete and row[following_tasks.c.taskstatus_id] in (TASKSTATUSES.Incomplete, None):
                        link = ("Undo", {"href": url_fwrd(row[tasktypes.c.undo_function], task_id=row[tasks.c.id])})
                    else:
                        link = ("", ())
                    
                    samples_involved = ""
                    if row[tasks.c.taskstatus_id] == TASKSTATUSES.Complete:
                        if row[tasktypes.c.edit_function] == "views.edit_volume":
                            samples_involved = ["{}ml EDTA".format(normalise(row[samples.c.volume]))] if row[samples.c.volume] else []
                            samples_involved += ["{}x10<sup>9</sup> cells/l".format(normalise(row[samples.c.cell_count]))] if row[samples.c.cell_count] else []
                            samples_involved = Markup(", ".join(samples_involved))
                        elif row[tasks.c.quantity]:
                            samples_involved = "{}{} {}".format(normalise(row[tasks.c.quantity], 2), "ml" if row[sampletypes.c.volume_based] else " x", row[sampletypes.c.name])

                rows += [tablerow((row[tasktypes.c.name], edit_url if row[tasks.c.taskstatus_id] == TASKSTATUSES.Incomplete else ()),
                                 (samples_involved, ()),
                                 (row[taskstatuses.c.name], ()),
                                 [user, ()],
                                 [strftime(row[tasks_users.c.datetime_completed], formatstring="%d %b %Y %H:%M"), ()],
                                 (row[tasks.c.comment], ()),
                                 link)]
            last_task_id = row[tasks.c.id]

    table = {"tabs": request_tabs(request_id, "Tasks"),
             "headings":  (("Task", ()), ("Samples", ()), ("Status", ()), ("Performed By", ()), ("Date", ()), ("Comment", ()), ("", ())), 
             "rows": rows,
             "buttons": (("Back", {"href": url_back()}),)}
    return render_template("table2.html", table=table, demographics=demographics, navbar=navbar())



@views.route("/requests/<int:request_id>/tests")
@login_required()
def request_tests(request_id):
    with engine().connect() as conn:
        demographics, request_id = request_table([requests.c.id == request_id, requests.c.deleted == False], conn)
        
        sql = select([tests.c.id, testtypes.c.name, testtypes.c.category, teststatuses.c.name, teststatuses.c.id, testcomments.c.comment, users.c.forename, \
                      users.c.surname, tests_users.c.datetime_selected, tests.c.deleted, testtypes.c.id]). \
                select_from(join(testtypes, tests, and_(tests.c.testtype_id == testtypes.c.id, tests.c.request_id == request_id), isouter=True). \
                            outerjoin(testcomments, and_(testcomments.c.testtype_id == testtypes.c.id, testcomments.c.request_id == request_id)). \
                            outerjoin(teststatuses, tests.c.teststatus_id == teststatuses.c.id). \
                            outerjoin(tests_users, tests_users.c.test_id == tests.c.id). \
                            outerjoin(users, users.c.id == tests_users.c.user_id)). \
                where(or_(tests.c.id != None, testcomments.c.id != None)).where(testtypes.c.visible == True). \
                order_by(tests.c.id == None, testtypes.c.category, testtypes.c.name)

        rows = []
        last_test_id = None
        for row in conn.execute(sql) or ():
            test_id = row[tests.c.id]
            user = initial_surname(row[users.c.surname], row[users.c.forename])
            if test_id == last_test_id and test_id is not None:
                rows[-1][0][3][0] += " / {}".format(user)
                rows[-1][0][4][0] = strftime(row[tests_users.c.datetime_selected], "%d/%m/%Y")
            else:
                last_test_id = test_id
                rows += [tablerow((row[testtypes.c.name], ()),
                                (row[testtypes.c.category], ()),
                                (row[teststatuses.c.name] or "", ()),
                                [user, ()],
                                [strftime(row[tests_users.c.datetime_selected], "%d/%m/%Y"), ()],
                                (row[testcomments.c.comment] or "", ()),
                                ("", ()),
                                deleted=row[tests.c.deleted],
                                **{"class": "clickable", "data": (("href", url_fwrd("selection.edit_test", request_id=request_id, testtype_id=row[testtypes.c.id])),)})]

    table = {"tabs": request_tabs(request_id, "Tests"), 
             "toolbar": (("", {"icon": "plus", "href": url_fwrd("selection.adhoc_tests", request_id=request_id)}),),
             "headings": (("Test", ()), ("Category", ()), ("Status", ()), ("Selected By", ()), ("Date", ()), ("Comment", ()), ("Date Requested", ())), 
             "rows": rows,
             "buttons": (("Back", {"href": url_back()}),)}
    return render_template("table2.html", table=table, demographics=demographics, navbar=navbar())



@views.route("/requests/<int:request_id>/reports")
@login_required()
def request_reports(request_id):
    with engine().connect() as conn:
        demographics, request_id, patient_id = request_table([requests.c.id == request_id, requests.c.deleted == False], conn, return_values=["request_id", "patient_id"])

        sql = select([reports.c.test, reports.c.report, reports.c.summary, reports.c.id, reports.c.date_taken, reports.c.date_reported, \
                      reports.c.lab_number]). \
                select_from(join(requests, patients, requests.c.patient_id == patients.c.id). \
                            join(reports, reports.c.patient_id == patients.c.id)). \
                where(and_(requests.c.id == request_id, reports.c.deleted == False)). \
                order_by(reports.c.date_taken)

        rows = []
        for row in conn.execute(sql):
            rows += [tablerow((row[reports.c.lab_number], ()),
                             (row[reports.c.test], {"href": url_for("views.report", report_id=row[reports.c.id], dir="X"), "new_tab": True}),
                             (strftime(row[reports.c.date_taken]), ()),
                             (Markup((row[reports.c.report] or "(Not ready)").replace("\n", "<br>")), {"summary": row[reports.c.summary] or "(Not ready)"}))]
    
        table = {"tabs": request_tabs(request_id, "Results"),
                 "headings": (("Lab Number", ()), ("Test", ()), ("Sample Date", ()), ("Report", ())), 
                 "rows": rows, 
                 "buttons": (("Back", {"href": url_back()}),)}
        return render_template("table2.html", table=table, demographics=demographics, navbar=navbar())



@views.route("/requests/<int:request_id>/exports")
@login_required()
def request_exports(request_id):
    with engine().connect() as conn:
        demographics, request_id, patient_id = request_table([requests.c.id == request_id, requests.c.deleted == False], conn, return_values=["request_id", "patient_id"])

        sql = select([reports.c.test, reports.c.id, reports.c.date_taken, reports.c.lab_number, reports.c.lab_number, reports.c.deleted, \
                    exports.c.destination, exports.c.details, exports.c.datetime_exported, exports.c.id]). \
                select_from(join(requests, patients, requests.c.patient_id == patients.c.id). \
                            join(reports, reports.c.patient_id == patients.c.id). \
                            join(exports, exports.c.report_id == reports.c.id)). \
                where(and_(requests.c.id == request_id, reports.c.deleted == False)). \
                order_by(reports.c.date_taken)

        rows = []
        for row in conn.execute(sql):
            rows += [tablerow((row[reports.c.lab_number], ()),
                             (row[reports.c.test], ()),
                             (strftime(row[reports.c.date_taken]), ()),
                             (row[exports.c.destination], ()),
                             (row[exports.c.details], ()),
                             (strftime(row[exports.c.datetime_exported]), ()),
                             deleted=row[reports.c.deleted],
                             **({"class": "clickable", "data": (("href", url_fwrd("views.resend_report", export_id=row[exports.c.id])),)} \
                                 if not row[reports.c.deleted] else {}), 
                             )]
            
        table = {"tabs": request_tabs(request_id, "Exports"),
                 "headings": (("Lab Number", ()), ("Test", ()), ("Sample Date", ()), ("Destination", ()), ("Details", ()), ("Export Date", ())), 
                 "rows": rows, 
                 "buttons": (("Back", {"href": url_back()}),)}
        return render_template("table2.html", table=table, demographics=demographics, navbar=navbar())



@views.route("/exports/<int:export_id>/resend", methods=["GET", "POST"])
@login_required()
def resend_report(export_id):    
    with engine().begin() as conn:
        sql = select([reports.c.test, reports.c.id, reports.c.date_taken, reports.c.lab_number, reports.c.lab_number, \
                    exports.c.destination, exports.c.details, exports.c.datetime_exported]). \
                select_from(join(reports, exports, exports.c.report_id == reports.c.id)). \
                where(and_(exports.c.id == export_id, reports.c.deleted == False))

        rows = []
        for row in conn.execute(sql):
            rows += [tablerow((row[reports.c.lab_number], ()),
                             (row[reports.c.test], ()),
                             (strftime(row[reports.c.date_taken]), ()),
                             (row[exports.c.destination], ()),
                             (row[exports.c.details], ()),
                             (strftime(row[exports.c.datetime_exported]), ()),
                             )]
        if len(rows) != 1:
            abort(Conflict)
        
        demographics = {"headings": (("Lab Number", ()), ("Test", ()), ("Sample Date", ()), ("Destination", ()), ("Details", ()), ("Export Date", ())), "rows": rows}
        
        if request.method == "POST":
            logic.reexport_report(export_id, conn)
            return redirect(url_back())

        else:
            message = ['Are you sure you want to resend this {} report to {}?'.format(row[reports.c.test], row[exports.c.destination])]
            buttons = (("Yes", {"submit": url_for("views.resend_report", export_id=export_id)}), ("No", {"href": url_back()}))

    return render_template("modal.html", message=message, buttons=buttons, demographics=demographics, navbar=navbar())



@views.route("/tasks/<int:task_id>/volume", methods=["GET", "POST"])
@login_required()
def edit_volume(task_id):
    with engine().begin() as conn:
        demographics, request_id = \
            request_table([tasks.c.id == task_id, tasktypes.c.edit_function == "views.edit_volume", tasks.c.taskstatus_id == TASKSTATUSES.Incomplete, requests.c.deleted == False], conn)
        
        sql = select([samples.c.id.label("sample_id"), samples.c.volume, samples.c.cell_count, tasks.c.comment]). \
                select_from(join(tasks, tasktypes, tasks.c.tasktype_id == tasktypes.c.id). \
                            join(substrates_sampletypes, substrates_sampletypes.c.substrate_id == tasktypes.c.substrate_id). \
                            join(samples, samples.c.sampletype_id == substrates_sampletypes.c.sampletype_id)). \
                where(and_(tasks.c.id == task_id, samples.c.request_id == tasks.c.request_id))
        old_data = conn.execute(sql).first() or {}

        form = VolumeForm(**({"formdata": request.form} if request.method == "POST" else {"data": {key: old_data[key] or None for key in ("volume", "cell_count", "comment")}}))            
        if request.method == "POST" and form.validate():
            logic.perform_volume(task_id, old_data, form.data, conn)
            return redirect(url_back())

    buttons=(("Save", {"submit": url_for("views.edit_volume", task_id=task_id)}), ("Cancel", {"href": url_back()}))
    return render_template("form2.html", form=form, buttons=buttons, demographics=demographics, heading="EDTA Quantification", navbar=navbar())



@views.route("/quantity_label", defaults={"sample_id": None}) # never used but needed to generate url stem
@views.route("/quantity_label/<int:sample_id>")
@login_required(history=False)
def quantity_label(sample_id):
    if sample_id == 0:
        return ""
    with engine().connect() as conn:
        sql = select([sampletypes.c.volume_based]).select_from(join(samples, sampletypes, samples.c.sampletype_id == sampletypes.c.id)).where(samples.c.id == sample_id)
        volume_based = conn.execute(sql).scalar()
        return "Volume (ml)" if volume_based else "Number"



@views.route("/tasks/<int:task_id>/perform", methods=["GET", "POST"])
@login_required()
def perform_task(task_id):
    with engine().begin() as conn:
        demographics, request_id = \
            request_table([tasks.c.id == task_id, tasktypes.c.edit_function == "views.perform_task", tasks.c.taskstatus_id == TASKSTATUSES.Incomplete, requests.c.deleted == False], conn)
        
        sql = select([samples.c.id, samples.c.number, sampletypes.c.name, tasks.c.comment, tasktypes.c.name]). \
                select_from(join(tasks, tasktypes, tasks.c.tasktype_id == tasktypes.c.id). \
                            join(substrates_sampletypes, substrates_sampletypes.c.substrate_id == tasktypes.c.substrate_id). \
                            join(samples, and_(samples.c.sampletype_id == substrates_sampletypes.c.sampletype_id, samples.c.request_id == tasks.c.request_id)). \
                            join(sampletypes, sampletypes.c.id == substrates_sampletypes.c.sampletype_id)). \
                where(tasks.c.id == task_id). \
                order_by(substrates_sampletypes.c.order)
        rows = list(conn.execute(sql))
        row = rows[0]
        
        form = TaskForm(**({"formdata": request.form} if request.method == "POST" else {"data": {"comment": row[tasks.c.comment]}}))
        form.sample_id.choices = [(0, "")] + list(OrderedDict(((row[samples.c.id], row[sampletypes.c.name]), None) for row in rows).keys())
        if request.method == "POST" and form.validate():
            new_data = form.data
            logic.perform_task(task_id, conn, taskcompleted=bool(new_data["sample_id"]), **new_data)
            return redirect(url_back())                
        
    buttons=(("Save", {"submit": url_for("views.perform_task", task_id=task_id)}), ("Cancel", {"href": url_back()}))
    return render_template("form_task.html", form=form, buttons=buttons, demographics=demographics, heading=row[tasktypes.c.name], navbar=navbar())



@views.route("/tasks/<int:task_id>/unperform", methods=["GET", "POST"])
@login_required()
def unperform_task(task_id):    
    with engine().begin() as conn:
        demographics, request_id = \
            request_table([tasks.c.id == task_id, tasktypes.c.undo_function == "views.unperform_task", tasks.c.taskstatus_id != TASKSTATUSES.Incomplete, requests.c.deleted == False], conn)
        
        if request.method == "POST":
            logic.unperform_task(request_id, task_id, conn)
            return redirect(url_back())

        else:
            sql = select([tasktypes.c.name]).select_from(join(tasks, tasktypes, tasks.c.tasktype_id == tasktypes.c.id)).where(tasks.c.id == task_id)
            tasktype_name = conn.execute(sql).scalar()
            message = ['Are you sure you want to undo "{}"?'.format(tasktype_name)]
            buttons = (("Undo", {"submit": url_for("views.unperform_task", task_id=task_id)}), ("Cancel", {"href": url_back()}))

    return render_template("modal.html", message=message, buttons=buttons, demographics=demographics, navbar=navbar())



@views.route("/reports/<int:report_id>", methods=["GET"])
@login_required()
def report(report_id):
    with engine().begin() as conn:
        row = conn.execute(report_sql(report_id)).first() or abort(NotFound)
        row = dict(row)
        
    if row["filename"]:
        path = os.path.join(current_app.instance_path, "reports",  row["filename"])
        if os.path.isfile(path):
            return send_file(path)
    
    return send_file(BytesIO(report_pdf(row)), mimetype="application/pdf")



@views.route("/setdate", methods=["GET", "POST"])
@login_required(root=True)
def setdate():
    form = DateForm(request.form)
    if request.method == "POST" and form.validate():
        session["date"] = form.date.data

    return render_template("form2.html", form=form, buttons=(("Set", {"submit": url_for("views.setdate")}),), navbar=navbar())



