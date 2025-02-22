import os
import shutil
import threading
import webbrowser
import logging
from flask import Flask, request, render_template, send_from_directory, redirect, url_for
from PyQt5 import QtWidgets, uic, QtCore
from PyQt5.QtWidgets import QMessageBox, QTableWidgetItem
from PyQt5.QtCore import pyqtSignal
from werkzeug.serving import make_server

class ControlledFlaskServer:
    def __init__(self, app, host="0.0.0.0", port=5000):
        self.app = app
        self.host = host
        self.port = port
        self.server = None
        self.thread = None

    def start(self):
        self.server = make_server(self.host, self.port, self.app)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def stop(self):
        if self.server:
            self.server.shutdown()
            self.thread.join()
            self.server = None
            self.thread = None

class WIFTPlugin(QtWidgets.QWidget):
    file_added = pyqtSignal()

    def __init__(self, parent=None, logger=None):
        super().__init__(parent)
        self.logger = logger or logging.getLogger("WIFTPlugin")
        self.server_running = threading.Event()
        self.app = Flask(
            __name__,
            template_folder=os.path.join(os.path.dirname(__file__), "WebPage"),
            static_folder=os.path.join(os.path.dirname(__file__), "WebPage")
        )
        self.flask_server = ControlledFlaskServer(self.app)
        self.temp_dir = os.path.join(os.path.dirname(__file__), "WebPage/temp_files")
        os.makedirs(self.temp_dir, exist_ok=True)
        self.file_added.connect(self.update_file_table)
        self.setup_ui()
        self.configure_routes()
        self.logger.info("Wi-Fi File Transfer Plugin initialized.")

    def setup_ui(self):
        try:
            ui_path = os.path.join(os.path.dirname(__file__), "WIFT.ui")
            uic.loadUi(ui_path, self)
            self.start_server_button = self.findChild(QtWidgets.QPushButton, "start_server")
            self.label_status = self.findChild(QtWidgets.QLabel, "label_status")
            self.display_url = self.findChild(QtWidgets.QLineEdit, "display_url")
            self.open_site_button = self.findChild(QtWidgets.QPushButton, "open_site")
            self.file_table = self.findChild(QtWidgets.QTableWidget, "file_table")
            self.start_server_button.clicked.connect(self.toggle_server)
            self.open_site_button.clicked.connect(self.open_website)

            # Set up the table
            self.file_table.setColumnCount(3)
            self.file_table.setHorizontalHeaderLabels(["Filename", "Type", "Actions"])
            self.file_table.horizontalHeader().setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)
            self.file_table.horizontalHeader().setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeToContents)
            self.file_table.horizontalHeader().setSectionResizeMode(2, QtWidgets.QHeaderView.ResizeToContents)
            self.update_status("Stopped", "red")
            self.update_file_table()
        except Exception as e:
            self.logger.error(f"Error setting up the UI: {str(e)}")
            QMessageBox.critical(self, "UI Setup Error", f"Error setting up the UI: {str(e)}")
            raise

    def configure_routes(self):
        @self.app.route('/')
        def index():
            files = os.listdir(self.temp_dir)
            return render_template('index.html', files=files)

        @self.app.route('/upload', methods=['POST'])
        def upload_file():
            file = request.files.get('file')
            if file and file.filename:
                file.save(os.path.join(self.temp_dir, file.filename))
                QtCore.QMetaObject.invokeMethod(self, "file_added", QtCore.Qt.QueuedConnection)
                self.logger.info(f"File uploaded: {file.filename}")
                return redirect(url_for('index'))
            self.logger.warning("No file selected for upload.")
            return "No file selected", 400

        @self.app.route('/download/<filename>')
        def download_file(filename):
            return send_from_directory(self.temp_dir, filename, as_attachment=True)

        @self.app.route('/delete/<filename>', methods=['POST'])
        def delete_file(filename):
            file_path = os.path.join(self.temp_dir, filename)
            if os.path.exists(file_path):
                os.remove(file_path)
                self.file_added.emit()
                self.logger.info(f"File deleted: {filename}")
                return redirect(url_for('index'))
            self.logger.warning(f"File not found for deletion: {filename}")
            return "File not found", 404

    def toggle_server(self):
        if self.server_running.is_set():
            self.stop_server()
            self.start_server_button.setText("Start Server")
        else:
            self.start_flask_server()
            self.start_server_button.setText("Stop Server")

    def start_flask_server(self):
        try:
            ip_address = self.get_local_ip_address()
            self.display_url.setText(f"http://{ip_address}:5000")
            self.update_status("Running", "green")
            self.server_running.set()
            self.flask_server.start()
            self.logger.info("Flask server started.")
        except Exception as e:
            self.update_status("Problem!", "orange")
            self.logger.error(f"Error starting Flask server: {e}")
            self.server_running.clear()

    def stop_server(self):
        if self.server_running.is_set():
            self.flask_server.stop()
            self.server_running.clear()
            self.update_status("Stopped", "red")
            self.display_url.clear()
            self.logger.info("Flask server stopped.")

    def open_website(self):
        url = self.display_url.text()
        if url:
            webbrowser.open(url)
            self.logger.info(f"Opened website: {url}")
        else:
            QMessageBox.warning(self, "Error", "No URL to open!")
            self.logger.warning("Attempted to open website, but URL was empty.")

    def update_file_table(self):
        self.file_table.setRowCount(0)
        for filename in os.listdir(self.temp_dir):
            row_position = self.file_table.rowCount()
            self.file_table.insertRow(row_position)
            self.file_table.setItem(row_position, 0, QTableWidgetItem(filename))
            file_type = os.path.splitext(filename)[1][1:] or "Unknown"
            self.file_table.setItem(row_position, 1, QTableWidgetItem(file_type))
            button_widget = QtWidgets.QWidget()
            button_layout = QtWidgets.QHBoxLayout(button_widget)
            button_layout.setContentsMargins(0, 0, 0, 0)
            download_button = QtWidgets.QPushButton("Download")
            download_button.clicked.connect(lambda checked, f=filename: self.handle_download(f))
            delete_button = QtWidgets.QPushButton("Delete")
            delete_button.clicked.connect(lambda checked, f=filename: self.handle_delete(f))
            button_layout.addWidget(download_button)
            button_layout.addWidget(delete_button)
            self.file_table.setCellWidget(row_position, 2, button_widget)

    def handle_download(self, filename):
        file_path = os.path.join(self.temp_dir, filename)
        if os.path.exists(file_path):
            dest = os.path.join(os.path.expanduser("~"), "Downloads", filename)
            shutil.copy(file_path, dest)
            QMessageBox.information(self, "Download", f"File downloaded to {dest}")
            self.logger.info(f"File downloaded: {filename} to {dest}")
        else:
            QMessageBox.warning(self, "Download Error", "File not found!")
            self.logger.warning(f"Attempted to download missing file: {filename}")

    def handle_delete(self, filename):
        file_path = os.path.join(self.temp_dir, filename)
        if os.path.exists(file_path):
            os.remove(file_path)
            self.file_added.emit()
            QMessageBox.information(self, "Delete", f"File '{filename}' deleted.")
            self.logger.info(f"File deleted: {filename}")
        else:
            QMessageBox.warning(self, "Delete Error", "File not found!")
            self.logger.warning(f"Attempted to delete missing file: {filename}")

    def cleanup_temp_files(self):
        for filename in os.listdir(self.temp_dir):
            try:
                os.remove(os.path.join(self.temp_dir, filename))
                self.logger.info(f"Temporary file cleaned up: {filename}")
            except OSError as e:
                self.logger.error(f"Error deleting temporary file {filename}: {e}")

    def update_status(self, status, color):
        self.label_status.setText(status)
        self.label_status.setStyleSheet(f"color: {color};")

    def get_local_ip_address(self):
        import socket
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
        except Exception:
            return "127.0.0.1"
        finally:
            s.close()

    def hideEvent(self, event):
        self.stop_server()
        super().hideEvent(event)

def main(parent_widget=None, parent_logger=None):
    try:
        logger = parent_logger.getChild("WIFT") if parent_logger else logging.getLogger("WIFT")
        logger.info("Initializing Wi-Fi File Transfer Plugin.")
        return WIFTPlugin(parent_widget, logger)
    except Exception as e:
        if parent_logger:
            parent_logger.error(f"Failed to load Wi-Fi File Transfer Plugin: {e}")
        QMessageBox.critical(None, "Plugin Error", f"Failed to load Wi-Fi File Transfer Plugin: {str(e)}")
        return None
