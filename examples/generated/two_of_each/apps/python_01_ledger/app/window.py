from PyQt6 import QtWidgets, QtCore
from app.db import connect_db
from app.theme import set_theme

class Window(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Ledger")
        self.setGeometry(100, 100, 800, 600)
        self.status_bar = self.statusBar()
        self.status_bar.showMessage("Ready")
        self.create_widgets()
        self.create_connections()
        self.load_data()
        self.set_theme()

    def create_widgets(self):
        self.table = QtWidgets.QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["Date", "Description", "Amount", "Category"])
        self.setCentralWidget(self.table)

    def create_connections(self):
        pass

    def load_data(self):
        conn = connect_db()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM entries")
        rows = cursor.fetchall()
        self.table.setRowCount(len(rows))
        for i, row in enumerate(rows):
            for j, data in enumerate(row):
                self.table.setItem(i, j, QtWidgets.QTableWidgetItem(str(data)))
        conn.close()

    def set_theme(self):
        set_theme(self)

    def add_entry(self):
        pass

    def search_entries(self):
        pass

    def calculate_totals(self):
        pass