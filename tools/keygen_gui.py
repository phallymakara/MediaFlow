from datetime import date, datetime, timedelta
from pathlib import Path
import sys

# Ensure project root is available for imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.services.license import LicenseService

GUI_STYLESHEET = """
QMainWindow {
    background-color: #1a1b26;
    color: #c0caf5;
}
QWidget {
    font-family: 'Segoe UI', Arial, sans-serif;
    font-size: 13px;
    color: #c0caf5;
}
QLabel {
    color: #a9b1d6;
}
QLineEdit, QComboBox {
    background-color: #24283b;
    border: 1px solid #414868;
    border-radius: 4px;
    padding: 6px 10px;
    color: #c0caf5;
}
QLineEdit:focus, QComboBox:focus {
    border: 1px solid #7aa2f7;
}
QPushButton {
    background-color: #7aa2f7;
    color: #15161e;
    font-weight: bold;
    border: none;
    border-radius: 4px;
    padding: 8px 14px;
}
QPushButton:hover {
    background-color: #89b4fa;
}
QPushButton:pressed {
    background-color: #5c7ee0;
}
QPushButton#copyBtn {
    background-color: #414868;
    color: #c0caf5;
}
QPushButton#copyBtn:hover {
    background-color: #565f89;
}
"""


class KeygenWindow(QMainWindow):
    """Admin key generator desktop window."""

    def __init__(self) -> None:
        """Initialize key generator window."""
        super().__init__()
        self.setWindowTitle("MediaFlow License Generator")
        self.resize(480, 320)
        self.setStyleSheet(GUI_STYLESHEET)

        central_widget = QWidget(self)
        self.setCentralWidget(central_widget)

        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(24, 20, 24, 20)
        main_layout.setSpacing(16)

        title_label = QLabel("MediaFlow License Generator")
        title_label.setStyleSheet("font-size: 16px; font-weight: bold; color: #7aa2f7;")
        main_layout.addWidget(title_label)

        form_layout = QFormLayout()
        form_layout.setSpacing(12)

        self.duration_combo = QComboBox()
        self.duration_combo.addItems([
            "30 Days (1 Month)",
            "7 Days (Trial)",
            "90 Days (3 Months)",
            "365 Days (1 Year)",
            "Lifetime (Permanent)",
        ])
        form_layout.addRow("Duration:", self.duration_combo)

        self.user_input = QLineEdit()
        self.user_input.setPlaceholderText("e.g. John Doe, customer@email.com")
        form_layout.addRow("Customer Name / ID:", self.user_input)

        self.tier_combo = QComboBox()
        self.tier_combo.addItems(["Standard", "Pro"])
        form_layout.addRow("Tier:", self.tier_combo)

        main_layout.addLayout(form_layout)

        # Output key display
        self.key_output = QLineEdit()
        self.key_output.setReadOnly(True)
        self.key_output.setPlaceholderText("MDFL-XXXX-XXXX-XXXX-XXXX")
        self.key_output.setStyleSheet(
            "font-family: Consolas, monospace; font-size: 13px; font-weight: bold; color: #9ece6a;"
        )
        main_layout.addWidget(self.key_output)

        # Action buttons
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)

        self.generate_btn = QPushButton("Generate Key")
        self.generate_btn.clicked.connect(self._on_generate)
        btn_layout.addWidget(self.generate_btn)

        self.copy_btn = QPushButton("Copy to Clipboard")
        self.copy_btn.setObjectName("copyBtn")
        self.copy_btn.clicked.connect(self._on_copy)
        btn_layout.addWidget(self.copy_btn)

        main_layout.addLayout(btn_layout)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("font-size: 12px; color: #9ece6a;")
        main_layout.addWidget(self.status_label)

    def _on_generate(self) -> None:
        """Handle key generation request."""
        duration_idx = self.duration_combo.currentIndex()
        days_map = {
            0: 30,
            1: 7,
            2: 90,
            3: 365,
            4: None,  # Lifetime
        }
        days = days_map.get(duration_idx)
        exp_date: date | None = None
        if days:
            exp_date = (datetime.now() + timedelta(days=days)).date()

        tier = self.tier_combo.currentText().lower()
        user = self.user_input.text().strip()

        key = LicenseService.generate_key(
            expires_at=exp_date,
            tier=tier,
            uid=user,
        )

        self.key_output.setText(key)
        exp_text = exp_date.strftime("%Y-%m-%d") if exp_date else "Permanent"
        self.status_label.setText(f"Generated: valid until {exp_text}")
        self.status_label.setStyleSheet("font-size: 12px; color: #9ece6a;")

    def _on_copy(self) -> None:
        """Copy generated key to system clipboard."""
        key = self.key_output.text().strip()
        if key:
            clipboard = QApplication.clipboard()
            clipboard.setText(key)
            self.status_label.setText("Copied license key to clipboard.")
            self.status_label.setStyleSheet("font-size: 12px; color: #7aa2f7;")


def main() -> None:
    """Launch keygen GUI application."""
    app = QApplication(sys.argv)
    window = KeygenWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
