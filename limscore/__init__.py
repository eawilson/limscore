import os
import glob
from datetime import date

from flask import (Flask,
                   Blueprint)
from flask.json.tag import JSONTag

from .models import create_engine
from .admin import app as admin
from .utils import (engine,
                    url_fwrd,
                    url_back,
                    login_required,
                    navbar,
                    render_page,
                    render_template,
                    abort,
                    valid_groups,
                    utcnow,
                    initial_surname,
                    surname_forename,
                    tablerow,
                    sign_cookie,
                    unique_violation_or_reraise,
                    iso8601_to_utc)
from .wrappers import (Local,
                       Attr)
from .i18n import i18n_init

__all__ = ["utcnow",
           "Local",
           "Attr",
           "login_required",
           "engine",
           "abort",
           "tablerow",
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



def init_app(app):
    instance_path = app.instance_path

    config_files = glob.glob(os.path.join(instance_path, "*.cfg"))
    if len(config_files) == 0:
        msg = f"No configuration file found in {instance_path}."
        raise RuntimeError(msg)
    elif len(config_files) > 1:
        msg = f"Multiple configuration files found in {instance_path}."
        raise RuntimeError(msg)
    else:
        config_file = config_files[0]

    config = {}
    with open(config_file, "rt") as f:
        exec(f.read(), config)
    
    if "SECRET_KEY" not in config:
        with open(config_file, "a") as f:
            secret_key = os.urandom(16)
            f.write(f"\nSECRET_KEY = {secret_key}\n")
    
    if not hasattr(app, "extensions"):
        app.extensions = {}
    app.config.from_pyfile(config_file)
            
    db_url = config["DB_URL"]
    if db_url.startswith("sqlite:///") and db_url[10] != "/":
        cwd = os.getcwd()
        os.chdir(instance_path)
        db_path = os.path.abspath(db_url[10:])
        db_url = f"sqlite:///{db_path}"
        app.config["DB_URL"] = db_url
        os.chdir(cwd)
    
    #with app.app_context():
        #logger.initialise()
    
    app.extensions["engine"] = create_engine(db_url)
    
    class TagDate(JSONTag):
        __slots__ = ('serializer',)
        key = ' de'
        
        def check(self, value):
            return isinstance(value, date)

        def to_json(self, value):
            return value.toordinal()

        def to_python(self, value):
            return date.fromordinal(value)

    try: # exception will only occur with reloading in development server
        app.session_interface.serializer.register(TagDate)
    except KeyError:
        pass

    resources = Blueprint("core", 
                          __name__, 
                          template_folder="templates", 
                          static_folder="static", 
                          url_prefix="/core")
    app.register_blueprint(resources)
    
    from .auth import app as auth
    app.register_blueprint(auth)

    if not app.debug:
        app.config.update(SESSION_COOKIE_SECURE=True,
                          SESSION_COOKIE_HTTPONLY=True,
                          SESSION_COOKIE_SAMESITE='Lax')
        
        @app.after_request
        def security_headers(response):
            #response.headers['Strict-Transport-Security'] = \
            #    'max-age=31536000; includeSubDomains'
            response.headers['Content-Security-Policy'] = "default-src 'self'"
            response.headers['X-Content-Type-Options'] = 'nosniff'
            response.headers['X-Frame-Options'] = 'SAMEORIGIN'
            response.headers['X-XSS-Protection'] = '1; mode=block'
            return response
    
    i18n_init(app)





