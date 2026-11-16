"""Qorong'i tema: #111318 fon, #1B1F27 panel, #F6B84A tanlov, #3CB8B0 audio, #A78BFA AI."""
STYLESHEET = """
* { font-family: "Inter", "Segoe UI", "Noto Sans", sans-serif; font-size: 12px; color: #d9deea; }
QMainWindow, QDialog, QWidget { background: #111318; }
QMenuBar, QMenu { background: #161922; } QMenu::item:selected, QMenuBar::item:selected { background: #2a3142; }
QTabWidget::pane { border: 1px solid #262c3a; } QTabBar::tab { background: #1B1F27; padding: 6px 12px; }
QTabBar::tab:selected { background: #262c3a; color: #F6B84A; }
QListWidget, QScrollArea, QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox { background: #1B1F27; border: 1px solid #2a3142; border-radius: 4px; padding: 3px; }
QListWidget::item:selected { background: #2f3850; color: #F6B84A; }
QPushButton { background: #232a39; border: 1px solid #323b52; border-radius: 5px; padding: 5px 10px; }
QPushButton:hover { border-color: #F6B84A; } QPushButton:pressed { background: #F6B84A; color: #111318; }
QGroupBox { border: 1px solid #262c3a; border-radius: 6px; margin-top: 10px; padding-top: 8px; }
QGroupBox::title { subcontrol-origin: margin; left: 8px; color: #F6B84A; }
QFrame#fx { background: #161922; border: 1px solid #262c3a; border-radius: 6px; }
QLabel#preview { background: #000; border: 1px solid #262c3a; border-radius: 6px; color: #667; }
QLabel#tc { font-family: "Consolas", "Menlo", monospace; font-size: 14px; color: #F6B84A; }
QLabel#hint { color: #8a93a6; font-size: 11px; }
QSlider::groove:horizontal { height: 4px; background: #2a3142; border-radius: 2px; }
QSlider::handle:horizontal { background: #F6B84A; width: 12px; margin: -5px 0; border-radius: 6px; }
QProgressBar { border: 1px solid #2a3142; border-radius: 4px; text-align: center; }
QProgressBar::chunk { background: #F6B84A; }
QCheckBox::indicator:checked { background: #F6B84A; border: 1px solid #F6B84A; }
QStatusBar { background: #161922; }
"""

STYLESHEET += """
QToolBar {background:#161922;spacing:12px;border-bottom:1px solid #343b49;padding:5px;}
QToolButton {background:#252c38;border:1px solid #343b49;border-radius:5px;padding:10px 14px;font-weight:600;}
QToolButton:hover {color:#F6B84A;border-color:#F6B84A;}
QListWidget::item{padding:8px;border-bottom:1px solid #272e3a;}
QPlainTextEdit {background:#0e1117;border:1px solid #303847;border-radius:6px;padding:8px;font-family:Consolas;color:#bac4d4;}
QPushButton:disabled{color:#667184;background:#171c25;}
"""
