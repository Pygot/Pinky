from PySide6.QtCore import QTimer, Qt, QRunnable, QThreadPool, Signal, QObject, Slot
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QTextEdit, QLabel, QMessageBox, QLineEdit, QFormLayout, QTabWidget
)

import requests
import pytchat
import json
import sys
import os

CONFIG_FILE = "config.json"
DEFAULT_CONFIG = {"video_id": "1MkMVdZXxWE", "cmd_prefix": ""}
FONT_SIZE = 15



class WorkerSignals(QObject):
    """
    Defines and manages signals used for communication between worker threads
    and the main thread.

    This class is designed to handle custom signals for thread-safe communication.
    It provides a signal for indicating the completion of a task with additional
    information about the task's outcome.

    :ivar finished: A signal emitted when a task is completed, providing a
        boolean indicating success and a string message for further details.
    :type finished: Signal
    """
    finished = Signal(bool, str)



class UsernameValidator(QRunnable):
    """
    Represents a task running in a separate thread to validate a given username against
    an external API.

    This class uses an external API to validate the existence of a username.
    It is designed to run as a background task using QRunnable. A username is validated
    by sending a POST request to a specific API endpoint. The result of the validation
    is emitted back through signals for further handling. The class handles potential
    network and JSON parsing errors that may occur during the process.

    :ivar username: The username to validate.
    :type username: str
    :ivar signals: Signals used to emit the results of the username validation task.
    :type signals: WorkerSignals
    """
    def __init__(self, username):
        super().__init__()
        self.username = username
        self.signals = WorkerSignals()


    def run(self):
        try:
            response = requests.post(
                url='https://users.roproxy.com/v1/usernames/users',
                json={'usernames': [self.username], 'excludeBannedUsers': True},
                timeout=2
            )
            try:
                data = response.json()
                result = data.get('data') and len(data['data']) > 0
            except Exception as jex:
                print(f"[UsernameValidator] JSON error: {jex}")
                result = False
        except Exception as rex:
            print(f"[UsernameValidator] Request error: {rex}")
            result = False

        self.signals.finished.emit(result, self.username)



class ChatApp(QMainWindow):
    """
    GUI application for tracking YouTube chat participants based on specific commands.

    This application enables users to monitor YouTube chat messages, validate usernames
    from chat based on a custom command prefix, and record unique participants. Users
    can configure settings such as the YouTube video ID and the command prefix for
    detecting usernames via an intuitive GUI. The application relies on polling chat
    messages in real-time to capture and process usernames.

    The application includes functional controls such as starting/stopping the chat
    monitoring and processing subsequent usernames. Additionally, it features persistent
    configuration storage, with the ability to load and save settings to a local file.

    :ivar config: Application configuration dictionary containing saved settings,
        such as the YouTube video ID and command prefix.
    :type config: dict
    :ivar chat: Instance of the YouTube chat client created for retrieving chat
        messages. Initialized when chat monitoring starts.
    :type chat: Optional[pytchat.LiveChat]
    :ivar participants: A set containing the unique validated participants extracted
        from the chat.
    :type participants: set
    :ivar running: A boolean flag indicating whether the chat monitoring process is
        active.
    :type running: bool
    :ivar paused: A boolean flag signifying whether the username processing is paused
        and awaiting user interaction to proceed to the next username.
    :type paused: bool
    :ivar pending_validations: A set of usernames pending validation during the chat
        monitoring process.
    :type pending_validations: set
    :ivar threadpool: A thread pool for executing asynchronous username validation
        tasks in parallel.
    :type threadpool: QThreadPool
    :ivar chat_timer: A timer instance for periodically polling chat messages from the
        YouTube live chat in real-time.
    :type chat_timer: QTimer
    """
    def __init__(self):
        super().__init__()
        self.setWindowTitle("YouTube Chat Participant Tracker")
        self.resize(600, 400)
        self.config = self._load_config()

        self.chat = None
        self.participants = set()
        self.running = False
        self.paused = False
        self.pending_validations = set()

        self.threadpool = QThreadPool()

        self._setup_ui()

        self.chat_timer = QTimer(self)
        self.chat_timer.timeout.connect(self._poll_chat)
        self.chat_timer.setInterval(1000)


    def _load_config(self):
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, 'r') as f:
                    return json.load(f)
            except Exception as e:
                print(f"Failed to load config: {e}")

        with open(CONFIG_FILE, 'w') as f:
            json.dump(DEFAULT_CONFIG, f, indent=4)

        return DEFAULT_CONFIG.copy()


    def _save_config(self):
        new_config = {
            "video_id": self.video_id_input.text().strip(),
            "cmd_prefix": self.cmd_prefix_input.text().strip()
        }

        try:
            with open(CONFIG_FILE, 'w') as f:
                json.dump(new_config, f, indent=4)
            self.config = new_config
            self.statusBar().showMessage("Configuration saved")
            return True
        except Exception as e:
            self.statusBar().showMessage("Error saving configuration")
            QMessageBox.warning(self, "Error", "Failed to save configuration")
            return False


    def _setup_ui(self):
        main_widget = QWidget()
        main_layout = QVBoxLayout(main_widget)

        tabs = QTabWidget()
        chat_tab = QWidget()
        config_tab = QWidget()

        chat_layout = QVBoxLayout(chat_tab)

        self.username_display = QTextEdit()
        self.username_display.setReadOnly(True)
        font = self.username_display.font()
        font.setPointSize(FONT_SIZE)
        self.username_display.setFont(font)
        chat_layout.addWidget(self.username_display)

        controls = QHBoxLayout()

        self.start_button = QPushButton("Start Listening")
        self.start_button.clicked.connect(self.start_chat)

        self.stop_button = QPushButton("Stop Listening")
        self.stop_button.clicked.connect(self.stop_chat)
        self.stop_button.setEnabled(False)

        self.next_button = QPushButton("Next Username")
        self.next_button.clicked.connect(self.next_username)
        self.next_button.setEnabled(False)

        controls.addWidget(self.start_button)
        controls.addWidget(self.stop_button)
        controls.addWidget(self.next_button)
        controls.addStretch()

        chat_layout.addLayout(controls)

        config_layout = QVBoxLayout(config_tab)

        form = QFormLayout()
        self.video_id_input = QLineEdit(self.config.get("video_id", ""))
        form.addRow("YouTube Video ID:", self.video_id_input)

        self.cmd_prefix_input = QLineEdit(self.config.get("cmd_prefix", ""))
        form.addRow("Command Prefix:", self.cmd_prefix_input)

        config_layout.addLayout(form)

        save_layout = QHBoxLayout()
        save_button = QPushButton("Save Configuration")
        save_button.clicked.connect(self._save_config)
        save_layout.addWidget(save_button)
        save_layout.addStretch()

        config_layout.addLayout(save_layout)
        config_layout.addStretch()

        tabs.addTab(chat_tab, "Chat")
        tabs.addTab(config_tab, "Configuration")

        main_layout.addWidget(tabs)
        self.setCentralWidget(main_widget)
        self.statusBar().showMessage("Ready")


    def start_chat(self):
        try:
            self.statusBar().showMessage(f"Connecting to video ID: {self.config['video_id']}")
            self.chat = pytchat.create(video_id=self.config['video_id'])

            self.running = True
            self.paused = False
            self.pending_validations.clear()

            self.chat_timer.start()

            self.statusBar().showMessage(f"Connected to video: {self.config['video_id']}")

            self.start_button.setEnabled(False)
            self.stop_button.setEnabled(True)
            self.next_button.setEnabled(True)
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Error connecting to video: {str(e)}")
            self.statusBar().showMessage("Connection failed")


    def stop_chat(self):
        self.running = False
        self.chat_timer.stop()
        self.pending_validations.clear()

        self.statusBar().showMessage("Stopped")

        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.next_button.setEnabled(False)


    def next_username(self):
        self.paused = False
        self.statusBar().showMessage("Waiting for next username...")

    def _handle_validation_result(self, is_valid, username):
        self.pending_validations.discard(username)
        if not self.running:
            return

        if is_valid and username not in self.participants:
            self.participants.add(username)
            self._display_username(username)
            self.statusBar().showMessage(f"Valid username (Click next): {username}")
            self.paused = True
        else:
            self.statusBar().showMessage(f"Invalid username: {username}")


    def _poll_chat(self):
        if not self.running or self.paused:
            return

        try:
            if not self.chat.is_alive():
                self.statusBar().showMessage("Chat ended")
                self.stop_chat()
                return

            prefix = self.config.get('cmd_prefix', '')

            for item in self.chat.get().items:
                if not self.running:
                    break

                message = str(item.message).lower().replace(' ', '')

                if message.startswith(prefix) and 2 <= len(message) <= 20:
                    username = message.replace(prefix, '')
                    if (username not in self.participants and
                        username not in self.pending_validations):
                        self._validate_username_async(username)
                        return
        except Exception as e:
            print(f"[ChatApp] Error polling chat: {e}")
            self.statusBar().showMessage(f"Error: {str(e)}")
            self.stop_chat()


    def _validate_username_async(self, username):
        self.pending_validations.add(username)
        validator = UsernameValidator(username)
        validator.signals.finished.connect(self._handle_validation_result)
        self.threadpool.start(validator)


    def _display_username(self, username):
        self.username_display.append(f"{username}")
        self.statusBar().showMessage(f"Current username: {username}")



if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = ChatApp()
    window.show()
    sys.exit(app.exec())
