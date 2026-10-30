import sys
from PyQt6 import QtWidgets
from app.window import NoteCanvasWindow

if __name__ == '__main__':
    app = QtWidgets.QApplication(sys.argv)
    window = NoteCanvasWindow()
    window.show()
    sys.exit(app.exec())