import sys
from PyQt6 import QtWidgets, QtCore

class Window(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Counter")
        self.setGeometry(100, 100, 300, 200)
        self.initUI()

    def initUI(self):
        self.count = 0
        self.label = QtWidgets.QLabel(f"{self.count}", self)
        self.label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.label.setGeometry(100, 50, 100, 50)

        self.button = QtWidgets.QPushButton("Increment", self)
        self.button.setGeometry(100, 100, 100, 50)
        self.button.clicked.connect(self.increment)

    def increment(self):
        self.count += 1
        self.label.setText(f"{self.count}")