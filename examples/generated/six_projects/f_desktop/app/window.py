from PyQt6 import QtWidgets, QtCore, QtGui
from app.theme import apply_dark_theme
from app.db import NoteDatabase
from datetime import datetime
import uuid

class NoteCanvasWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("NoteCanvas")
        self.setGeometry(100, 100, 800, 600)
        self.notes_database = NoteDatabase()
        self.notes_database.create_table()
        self.init_ui()
        self.load_notes()
        self.setup_connections()

    def init_ui(self):
        self.create_menu_bar()
        self.create_toolbar()
        self.create_note_grid()
        self.create_search_box()
        self.apply_theme()

    def create_menu_bar(self):
        menu_bar = self.menuBar()
        file_menu = menu_bar.addMenu("&File")
        file_menu.addAction("&Add Note")
        file_menu.addAction("&Delete Note")
        file_menu.addAction("&Exit")

    def create_toolbar(self):
        toolbar = self.addToolBar("Note Toolbar")
        add_note_button = QtWidgets.QPushButton("+ Add Note")
        add_note_button.clicked.connect(self.add_note)
        toolbar.addWidget(add_note_button)

    def create_note_grid(self):
        self.note_grid = QtWidgets.QGridLayout()
        self.note_grid.setHorizontalSpacing(10)
        self.note_grid.setVerticalSpacing(10)
        self.central_widget = QtWidgets.QWidget()
        self.central_widget.setLayout(self.note_grid)
        self.setCentralWidget(self.central_widget)

    def create_search_box(self):
        self.search_box = QtWidgets.QLineEdit()
        self.search_box.setPlaceholderText("Search notes...")
        self.search_box.textChanged.connect(self.filter_notes)
        self.statusBar().addWidget(self.search_box)

    def apply_theme(self):
        apply_dark_theme(self)

    def setup_connections(self):
        self.add_note()
        self.delete_note()
        self.exit_app()

    def add_note(self):
        note = {
            "id": str(uuid.uuid4()),
            "title": "Untitled Note",
            "body": "",
            "color": "#0078D7",
            "pinned": False,
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat()
        }
        self.notes_database.create_note(note)
        self.load_notes()

    def delete_note(self):
        selected_notes = [self.note_grid.itemAt(i).widget() for i in range(self.note_grid.count()) if self.note_grid.itemAt(i).widget().isChecked()]
        for note in selected_notes:
            note_id = note.note_id
            self.notes_database.delete_note(note_id)
        self.load_notes()

    def filter_notes(self):
        query = self.search_box.text().lower()
        for i in range(self.note_grid.count()):
            note_card = self.note_grid.itemAt(i).widget()
            if query in note_card.title.lower() or query in note_card.body.lower():
                note_card.show()
            else:
                note_card.hide()

    def load_notes(self):
        self.note_grid.clear()
        notes = self.notes_database.get_all_notes()
        for note in notes:
            self.create_note_card(note)

    def create_note_card(self, note):
        card = QtWidgets.QWidget()
        card.setObjectName(f"note_card_{note['id']}")
        card.setStyleSheet("background-color: #2E2E2E; border: 1px solid #444; border-radius: 5px; padding: 10px;")
        card.setFixedHeight(150)
        card.setFixedWidth(250)
        card.setLayout(QtWidgets.QVBoxLayout())
        card.layout().setContentsMargins(0, 0, 0, 0)
        card.layout().setSpacing(5)

        # Color tag
        color_tag = QtWidgets.QLabel()
        color_tag.setStyleSheet(f"background-color: {note['color']}; border: 1px solid #444; border-radius: 5px; width: 15px; height: 15px;")
        color_tag.setFixedSize(15, 15)
        card.layout().addWidget(color_tag)

        # Title
        title_label = QtWidgets.QLabel(note['title'])
        title_label.setStyleSheet("color: #FFFFFF; font-weight: bold;")
        card.layout().addWidget(title_label)

        # Body
        body_label = QtWidgets.QLabel(note['body'])
        body_label.setStyleSheet("color: #CCCCCC;")
        card.layout().addWidget(body_label)

        # Pin button
        pin_button = QtWidgets.QPushButton()
        pin_button.setCheckable(True)
        pin_button.setChecked(note['pinned'])
        pin_button.setStyleSheet("border: none; background: transparent; padding: 0;")
        pin_button.clicked.connect(lambda _, n=note: self.toggle_pin(n))
        card.layout().addWidget(pin_button)

        # Delete button
        delete_button = QtWidgets.QPushButton("X")
        delete_button.setFixedSize(20, 20)
        delete_button.setStyleSheet("border: none; background: transparent; color: red;")
        delete_button.clicked.connect(lambda _, n=note: self.delete_note(n['id']))
        card.layout().addWidget(delete_button)

        # Add to grid
        self.note_grid.addWidget(card, 0, 0)

    def toggle_pin(self, note):
        note['pinned'] = not note['pinned']
        self.notes_database.update_note(note)
        self.load_notes()

    def exit_app(self):
        self.close()

    def delete_note(self, note_id):
        self.notes_database.delete_note(note_id)
        self.load_notes()