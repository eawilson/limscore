import pdb
import os
import sys
import importlib
from passlib.hash import bcrypt_sha256

from alembic.config import CommandLine
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from limscore import create_app, valid_groups
from limscore.models import groups, users, users_groups



def main():
    base_app = create_app(".")
    package_name = base_app.config["PACKAGE"]
    package = importlib.import_module(package_name)
    app = package.create_app(".")
    
    os.environ["DB_URL"] = app.config["DB_URL"]
    os.environ["MODELS"] = "{}.models".format(package_name)
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
                user_id = conn.execute(users.insert(). \
                            values(username="admin",
                                   forename="Admin",
                                   surname="Admin", 
                                   login_token="",
                                   password=bcrypt_sha256.hash("change_me"))). \
                            inserted_primary_key[0]

                conn.execute(users_groups.insert(). \
                    values(user_id=user_id,
                           group_id=group_id))



if __name__ == "__main__":
    main()
