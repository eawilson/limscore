import pdb
import os
import sys
from passlib.hash import bcrypt_sha256

from alembic.config import CommandLine
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from .utils import valid_groups
from .models import (users,
                     groups,
                     users_groups)
from limscore import logic



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
                group_id = conn.execute(select([groups.c.id]). \
                            where(groups.c.name == "Admin.Administrator")). \
                            first()[0]
                values = {"username": "admin",
                          "name": "A.Admin",
                          "forename": "Admin",
                          "surname": "Admin",
                          "password": bcrypt_sha256.hash("change_me")}
                sql = users.insert().values(**values)
                user_id = conn.execute(sql).inserted_primary_key[0]
                logic.session = {"id": user_id}
                logic.crudlog("users", user_id, "Created", values, conn)
                logic.edit_m2m(users,
                               user_id,
                               users_groups,
                               [group_id],
                               [],
                               [(group_id, "Admin.Administrator")],
                               conn)
