import sqlalchemy
import logging
import urllib.parse
from contextlib import contextmanager
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


class DatabaseClient:
    def __init__(self, db_type, database, username, password, host, port=None):
        self.db_type = db_type.lower()
        self.database = database
        self.username = username
        self.password = password
        self.host = host
        self.port = port
        self.logger = logging.getLogger(__name__)

        self.logger.info(f"Initializing DatabaseClient with db_type={db_type}, database={database}, username={username}, host={host}, port={port}")

        if self.db_type == 'mssql':
            driver = 'mssql+pymssql'
        elif self.db_type == 'mariadb':
            driver = 'mariadb+mariadbconnector'
        elif self.db_type == 'postgresql':
            driver = 'postgresql+psycopg2'
        else:
            raise ValueError(f"Invalid database type {self.db_type}")

        connection_string = f'{driver}://{urllib.parse.quote_plus(username)}:{urllib.parse.quote_plus(password)}@{urllib.parse.quote_plus(host)}:{urllib.parse.quote_plus(port)}/{urllib.parse.quote_plus(database)}'
        self.logger.info(
            "Database connection configured (credentials redacted): "
            f"driver={driver}, host={host}, port={port}, database={database}"
        )

        # pool_pre_ping helps avoid handing out stale connections.
        # pool_recycle mitigates long-lived connections being dropped by the server/network.
        self.engine = create_engine(
            connection_string,
            pool_pre_ping=True,
            pool_recycle=1800,
        )

        # Prefer a dedicated session factory so callers can reliably close sessions.
        self._SessionLocal = sessionmaker(bind=self.engine)

    def get_engine(self):
        return self.engine

    def get_connection(self):
        try:
            if self.engine:
                return self.engine.connect()
            self.logger.error("DatabaseClient not initialized properly. Engine is None. Check error from init.")
        except Exception as e:
            self.logger.error(f"Error connecting to database: {e}")

    def get_session(self):
        try:
            if self.engine:
                return self._SessionLocal()
            self.logger.error("DatabaseClient not initialized properly. Engine is None. Check error from init.")
        except Exception as e:
            self.logger.error(f"Error connecting to database: {e}")

    @contextmanager
    def session_scope(self):
        """
        Provide a transactional scope around a series of operations.

        Always closes the session (returning the connection to the pool).
        Rolls back on exception.
        """
        session = self.get_session()
        try:
            yield session
        except Exception:
            try:
                if session is not None:
                    session.rollback()
            finally:
                raise
        finally:
            try:
                if session is not None:
                    session.close()
            except Exception:
                pass

    def execute_sql(self, sql):
        try:
            with self.get_connection() as conn:
                res = conn.execute(sqlalchemy.text(sql))
                conn.commit()
                return res
        except Exception as e:
            self.logger.error(f"Error executing SQL: {e}")
