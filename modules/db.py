import pyodbc
from queue import Queue, Empty

class ConnectionPool:
    def __init__(self, size=5):
        self.size = size
        self.pool = Queue(maxsize=size)
        self.conn_str = (
            'DRIVER={ODBC Driver 17 for SQL Server};'
            'SERVER=127.0.0.1;'
            'port=1433;' 
            'DATABASE=MotionAnalysis;'
            'UID=MotionUser;'           
            'PWD=MotionUser;'      
            'TrustServerCertificate=yes;'
        )
        self.current_size = 0

    def _create_conn(self):
        return pyodbc.connect(self.conn_str)

    def get_conn(self):
        try:
            return self.pool.get_nowait()
        except Empty:
            if self.current_size < self.size:
                self.current_size += 1
                return self._create_conn()
            else:
                return self.pool.get(timeout=10)

    def release_conn(self, conn):
        try:
            self.pool.put_nowait(conn)
        except Exception:
            conn.close()
            self.current_size -= 1
db_pool = ConnectionPool(size=10)

def get_conn():
    return db_pool.get_conn()

def release_conn(conn):
    db_pool.release_conn(conn)