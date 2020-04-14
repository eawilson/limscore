import pdb
import os
import sys
from passlib.hash import bcrypt_sha256

from alembic.config import CommandLine
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from .utils import valid_groups
from .models import (users,
                     groups)
from . import logic, auth


def run_alembic(package):
    """ Wrapper around alembic. Is called from the instance folder containing
        the details of the database to be migrated. To allow multiple versions
        of the database on the same system (eg test and prod). Will add any
        additional groups referenced in the code to the database and will 
        prime an admin user if this is a new empty database.
    """
    app = package.create_app(".")
    os.environ["DB_URL"] = app.config["DB_URL"]
    os.environ["MODELS"] = "{}.models".format(package.__name__)
    os.chdir(os.path.dirname(package.__file__))
    CommandLine().main()
    
    if sys.argv[1] == "upgrade":
        with app.extensions["engine"].begin() as conn:
            for name in valid_groups:
                trans = conn.begin_nested()
                try:
                    conn.execute(groups.insert().values(name=name))
                    trans.commit()
                except IntegrityError:
                    trans.rollback()

            if conn.execute(select([users.c.id])).first() is None:
                email = app.config.get("ADMIN", None)
                if email is None:
                    print("Unable to create admin account as no ADMIN entry in config.")
                else:
                    group_id = conn.execute(select([groups.c.id]). \
                                where(groups.c.name == "Admin.Administrator")). \
                                scalar()
                    new = {"email": email,
                           "name": "A.Admin",
                           "forename": "Admin",
                           "surname": "Admin",
                           "groups": [group_id]}
                    group_id_choices = ((group_id, "Admin.Administrator"),)
                    
                    with app.test_request_context():
                        logic.crud(users, new, conn=conn, groups=group_id_choices)
                        auth.send_setpassword_email(email, conn)
                    print(f"Admin login emailed to {email}.")
