import sys
from PyQt6 import QtWidgets
from app.window import Window

if __name__ == '__main__':
    app = QtWidgets.QApplication(sys.argv)
    window = Window()
    window.show()
    sys.exit(app.exec())