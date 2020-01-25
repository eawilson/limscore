from sqlalchemy import MetaData, Table, Sequence, Column, Integer, String, DateTime, Boolean, ForeignKey, Numeric, UniqueConstraint, Date, CheckConstraint, ForeignKeyConstraint
import sqlalchemy

__all__ = ("metadata", "create_engine", "users", "users_groups", "groups", "logins", "sites")



convention = {"ix": "ix_%(column_0_label)s",
              "uq": "uq_%(table_name)s_%(column_0_name)s",
              "ck": "ck_%(table_name)s_%(constraint_name)s",
              "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
              "pk": "pk_%(table_name)s"
             }
metadata = MetaData(naming_convention=convention)



def create_engine(db_url, *args, **kwargs):
    
    engine = sqlalchemy.create_engine(db_url, *args, **kwargs)

    if db_url.startswith("sqlite://"):
        @sqlalchemy.event.listens_for(engine, "connect")
        def do_connect(dbapi_connection, connection_record):
            # disable pysqlite's emitting of the BEGIN statement entirely.
            # also stops it from emitting COMMIT before any DDL.
            dbapi_connection.isolation_level = None

        @sqlalchemy.event.listens_for(engine, "begin")
        def do_begin(conn):
            # emit our own BEGIN
            conn.execute("BEGIN")

    #@sqlalchemy.event.listens_for(engine, 'before_cursor_execute')
    #def receive_before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
        #if not statement.startswith("SELECT"):
            #print(statement, repr(parameters))
                
    return engine



users = Table("users", metadata,
    Column("id", Integer, primary_key=True),
    Column("username", String(30), unique=True, nullable=False),
    Column("forename", String(30), nullable=False),
    Column("surname", String(30), nullable=False),
    Column("email", String(100), unique=True, nullable=True),
    Column("password", String(100), nullable=True),
    Column("reset_datetime", String, nullable=True),
    Column("last_site_id", String, nullable=True),
    Column("login_token", String, default="", nullable=False),
    Column("deleted", Boolean(name="bool"), default=False, nullable=False))



groups = Table("groups", metadata,
    Column("id", Integer, primary_key=True),
    Column("name", String(30), unique=True, nullable=False),
    Column("order", Integer, default=0, nullable=False)) # highest order group is selected each time a user logs in
    


users_groups = Table("users_groups", metadata,
    Column("user_id", Integer, ForeignKey("users.id"), nullable=False),
    Column("group_id", Integer, ForeignKey("groups.id"), nullable=False),
    UniqueConstraint("user_id", "group_id"))
    


users_sites = Table("users_sites", metadata,
    Column("user_id", Integer, ForeignKey("users.id"), nullable=False),
    Column("site_id", Integer, ForeignKey("sites.id"), nullable=False),
    UniqueConstraint("user_id", "site_id"))



logins = Table("logins", metadata,
    Column("id", Integer, primary_key=True),
    Column("name", String(30), unique=True),
    Column("username", String(30)),
    Column("password", String(30)),
    Column("info", String))



sites = Table("sites", metadata,
    Column("id", Integer, primary_key=True, nullable=False),
    Column("name", String(30), unique=True, nullable=False),
    Column("order", Integer, default=0, nullable=False),
    Column("deleted", Boolean(name="bool"), default=False, index=True, nullable=False))



#configurations = Table("configurations", metadata,
    #Column("id", Integer, primary_key=True, nullable=False),
    #Column("name", String(30), unique=True, nullable=False),
    #Column("value", String, default="", nullable=False))


