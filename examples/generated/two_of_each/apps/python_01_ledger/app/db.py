import sqlite3
from dotenv import load_dotenv
import os

load_dotenv()

def connect_db():
    conn = sqlite3.connect("ledger.db")
    return conn