# ZfDash Architecture Documentation

This document provides a comprehensive overview of the internal architecture and workings of the ZfDash application (v1.7.5-Beta). It is intended for developers or users interested in understanding how the different components interact.

## Table of Contents

*   [1. Overview](#1-overview)
*   [2. Core Components](#2-core-components)
    *   [2.1 UI Layer](#21-ui-layer)
        *   [2.1.1 Desktop GUI (PySide6)](#211-desktop-gui-pyside6)
        *   [2.1.2 Web UI (Flask/Waitress/Flask-Login)](#212-web-ui-flaskwaitressflask-login)
    *   [2.2 Backend Daemon (`zfs_daemon.py`)](#22-backend-daemon-zfs_daemonpy)
    *   [2.3 Communication Mechanism](#23-communication-mechanism)
    *   [2.4 Core ZFS Logic](#24-core-zfs-logic)
    *   [2.5 Configuration Management](#25-configuration-management)
    *   [2.6 Utilities](#26-utilities)
    *   [2.7 Data Models](#27-data-models)
    *   [2.8 Runner Scripts](#28-runner-scripts)
*   [3. Workflow Walkthroughs](#3-workflow-walkthroughs)
    *   [3.1 Application Startup](#31-application-startup)
    *   [3.2 Daemon Launch via Polkit](#32-daemon-launch-via-polkit)
    *   [3.3 UI Request -> ZFS Command Execution](#33-ui-request---zfs-command-execution)
    *   [3.4 Web UI Authentication](#34-web-ui-authentication)
*   [4. Security Considerations](#4-security-considerations)
    *   [4.1 Daemon Privileges and Isolation](#41-daemon-privileges-and-isolation)
    *   [4.2 Communication Security](#42-communication-security)
    *   [4.3 Web UI Security](#43-web-ui-security)
    *   [4.4 Polkit Policy](#44-polkit-policy)
*   [5. Installation and Build Process](#5-installation-and-build-process)
*   [6. Key Files and Directories](#6-key-files-and-directories)
*   [7. Development Setup](#7-development-setup)

## 1. Overview

ZfDash aims to provide user-friendly interfaces (Desktop GUI and Web UI) for managing ZFS on Linux systems. A key architectural decision is the separation of the user interface (running as a standard user) from the privileged backend daemon (running as root) which executes the actual ZFS commands. This separation enhances security by minimizing the attack surface of the privileged process. Communication between the UI and the daemon is facilitated through secure mechanisms managed by the operating system.

## 2. Core Components

The application is modular, consisting of several Python scripts located primarily within the `src/` directory.

### 2.1 UI Layer

Provides the user interface for interaction.

#### 2.1.1 Desktop GUI (PySide6)

*   **File:** `src/main_window.py`, `src/widgets/`
*   **Technology:** PySide6 (Qt for Python)
*   **Description:** Implements the traditional desktop graphical user interface. Defines the main window layout, widgets (tree view, tables, dialogs), menus, and connects user actions (button clicks, menu selections) to the appropriate backend communication calls via `ZfsManager`.

#### 2.1.2 Web UI (Flask/Waitress/Flask-Login)

*   **Files:** `src/web_ui.py`, `src/templates/`, `src/static/`
*   **Technology:** Flask (web framework), Waitress (production WSGI server), Flask-Login (session management), Jinja2 (templating).
*   **Description:** Implements the web-based user interface accessible via a browser.
    *   `web_ui.py`: Contains Flask routes (`@app.route(...)`) that handle HTTP requests, render HTML templates using data fetched via `ZfsManager`, and process form submissions. It also manages user sessions and authentication using Flask-Login.
    *   `templates/`: HTML templates (using Jinja2 syntax) defining the structure and appearance of the web pages (e.g., `index.html`, `login.html`).
    *   `static/`: CSS stylesheets, JavaScript files, and images served directly by the web server.
    *   **Server:** Uses `waitress` for serving the Flask application in production environments (when installed as a service or run manually without `--debug`), replacing the Flask development server.

### 2.2 Backend Daemon (`zfs_daemon.py`)

*   **File:** `src/zfs_daemon.py`
*   **Technology:** Python Standard Library (multiprocessing, subprocess, os)
*   **Description:** This is the privileged component that runs as root. It is launched on demand by the UI via Polkit (`pkexec`).
    *   **Responsibilities:**
        *   Listens for commands from the UI process via a secure pipe.
        *   Parses incoming commands and arguments.
        *   Constructs and executes the corresponding `zfs` or `zpool` commands using `subprocess`.
        *   Captures the output (stdout, stderr) and exit code of the ZFS commands.
        *   Formats the results (or errors) into a JSON response.
        *   Sends the JSON response back to the UI process via another pipe.
        *   Handles credential management (reading/writing `credentials.json`, verifying passwords) for Web UI login and password changes.
        *   Manages its own lifecycle and cleanup.

### 2.3 Communication Mechanism

*   **Files:** `src/daemon_utils.py`, `src/zfs_manager.py`, `src/zfs_daemon.py`
*   **Technology:** Polkit (`pkexec`), OS Anonymous Pipes (`os.pipe()`)
*   **Description:** Defines how the UI (user process) communicates with the backend daemon (root process).
    *   **Initiation:** The UI (`ZfsManager` via `DaemonManager` in `daemon_utils.py`) uses Polkit (`pkexec`) to request the launch of `zfs_daemon.py` as root. Polkit verifies user authorization based on the installed policy file (`org.zfsgui.pkexec.daemon.launch.policy`).
    *   **Pipes:** Before launching the daemon via `pkexec`, the UI process creates two anonymous pipes using `os.pipe()`. The file descriptors for these pipes are passed to the `zfs_daemon.py` process via command-line arguments during the `pkexec` call.
        *   **UI -> Daemon Pipe:** Used by the UI to send JSON-formatted command requests to the daemon.
        *   **Daemon -> UI Pipe:** Used by the daemon to send JSON-formatted responses back to the UI.
    *   **Security:** Using kernel-managed anonymous pipes ensures that only the initiating UI process and the spawned daemon process can communicate. Other processes on the system cannot easily interfere or eavesdrop on this communication channel, unlike methods relying on user-writable sockets.

### 2.4 Core ZFS Logic

*   **Files:** `src/zfs_manager_core.py`, `src/zfs_manager.py`
*   **Description:** Encapsulates the logic for interacting with ZFS and managing the communication with the daemon.
    *   `zfs_manager_core.py`: Contains the `ZfsManagerCore` class. This class holds the actual state (pools, datasets, snapshots) retrieved from ZFS. It includes methods for parsing `zpool status`, `zfs list`, properties, etc., primarily by invoking ZFS commands directly (intended for scenarios where direct ZFS access is possible, although the primary mode now uses the daemon). *Note: Its role might be reduced now that most operations go via the daemon.*
    *   `zfs_manager.py`: Contains the `ZfsManager` class. This acts as the primary interface for the UIs (GUI and Web). It orchestrates calls to the backend daemon.
        *   It initializes the `DaemonManager` (`daemon_utils.py`) to handle daemon startup and communication.
        *   Provides high-level methods (e.g., `get_pools()`, `create_snapshot(name, recursive=False)`, `set_property(prop, value)`) that the UIs call.
        *   These methods formulate the command dictionary, send it to the daemon via the `DaemonManager`, wait for the response, parse it, and return the result or raise an exception.
        *   It might interact with `ZfsManagerCore` to manage cached state or perform purely informational parsing that doesn't require root.

### 2.5 Configuration Management

*   **File:** `src/config_manager.py`
*   **Technology:** Python Standard Library (configparser, os)
*   **Description:** Handles reading and writing user-specific application settings (not ZFS properties).
    *   Stores settings like window size/position, last selected items, logging preferences, etc.
    *   Uses a configuration file typically located at `~/.config/ZfDash/zfdash.ini`.

### 2.6 Utilities

*   **Files:** `src/utils.py`, `src/daemon_utils.py`
*   **Description:** Contain helper functions and classes used across the application.
    *   `utils.py`: General utility functions (e.g., formatting sizes, constants, helper dialogs).
    *   `daemon_utils.py`: Classes and functions specifically related to managing the daemon process life cycle and communication (e.g., `DaemonManager`, command formatting, pipe handling, Polkit interaction).

### 2.7 Data Models

*   **File:** `src/models.py`
*   **Description:** Defines simple data structures (often using basic Python dictionaries or simple classes) used to represent ZFS objects like pools, datasets, snapshots, and their properties within the application logic.

### 2.8 Runner Scripts

*   **Files:** `src/main.py`, `src/gui_runner.py`
*   **Description:** Entry points and initialization logic.
    *   `main.py`: The main entry point for the application. Parses command-line arguments (`--web`, `--daemon`, `--host`, `--port`, etc.). Based on the arguments, it either initializes the GUI (`gui_runner.py`) or the Web UI (`web_ui.py`). It's responsible for setting up the core `ZfsManager`.
    *   `gui_runner.py`: Contains the logic specific to initializing and running the PySide6 GUI application (`QApplication`, `MainWindow`).

## 3. Workflow Walkthroughs

### 3.1 Application Startup

1.  **User Execution:** The user runs `zfdash` (launcher script) or `python3 src/main.py [--web]`.
2.  **`main.py`:** Parses arguments.
3.  **`ZfsManager` Initialization:** Creates an instance of `ZfsManager`.
4.  **UI Initialization:**
    *   **GUI:** Calls `gui_runner.py` which sets up `QApplication` and shows `MainWindow`.
    *   **Web UI:** Calls `web_ui.initialize_web_app()`, configures Flask/Flask-Login, and starts the `waitress` server (or Flask dev server if `--debug`).
5.  **Initial Data Load:** The UI (GUI or Web UI's initial page load) typically triggers `ZfsManager` methods like `get_pools_datasets_snapshots()` to fetch initial data. This involves launching the daemon if not already running.

### 3.2 Daemon Launch via Polkit

1.  **First UI Request:** When `ZfsManager` needs to execute a privileged command for the first time (e.g., during initial data load), `DaemonManager` (`daemon_utils.py`) is invoked.
2.  **Pipe Creation:** `DaemonManager` creates two OS pipes (`os.pipe()`).
3.  **Polkit Request:** It constructs the `pkexec` command: `pkexec /path/to/installed/python /opt/zfdash/app/zfs_daemon.py --pipe-in <fd1> --pipe-out <fd2> [--log-file <path>]`.
4.  **Polkit Authentication:** The system's Polkit agent prompts the user for authentication (if required by policy and not already authorized).
5.  **Daemon Execution:** If authorized, Polkit executes `zfs_daemon.py` as root, passing the pipe file descriptors.
6.  **Daemon Initialization:** `zfs_daemon.py` parses its arguments, opens the pipes using the provided file descriptors, and enters its main listening loop.
7.  **Daemon Ready:** The `DaemonManager` confirms the daemon is running and ready to receive commands.

### 3.3 UI Request -> ZFS Command Execution

1.  **User Action:** User clicks "Create Snapshot" in the UI.
2.  **UI Handler:** The UI's event handler calls `zfs_manager.create_snapshot('pool/dataset', 'snap_name')`.
3.  **`ZfsManager`:** Formats a command dictionary: `{'command': 'create_snapshot', 'target': 'pool/dataset', 'name': 'snap_name', 'recursive': False}`.
4.  **`DaemonManager`:** Sends the JSON representation of the command dictionary over the `UI -> Daemon` pipe.
5.  **`zfs_daemon.py` (Daemon):**
    *   Reads the JSON command from its input pipe.
    *   Parses the command ('create_snapshot').
    *   Constructs the ZFS shell command: `zfs snapshot pool/dataset@snap_name`.
    *   Executes the command using `subprocess.run()`.
    *   Captures `stdout`, `stderr`, and the `returncode`.
    *   Formats a JSON response: `{'success': True, 'stdout': '', 'stderr': ''}` or `{'success': False, 'error': '...', 'stderr': '...'}`.
    *   Sends the JSON response back over the `Daemon -> UI` pipe.
6.  **`DaemonManager`:** Reads the JSON response from the pipe.
7.  **`ZfsManager`:** Parses the response. If `success` is `True`, it might trigger a data refresh. If `False`, it raises an exception or returns an error indicator.
8.  **UI Update:** The UI receives the result, updates the snapshot list (on success), or displays an error message (on failure).

### 3.4 Web UI Authentication

1.  **Access Login Page:** User navigates to the Web UI URL. Flask-Login detects no active session and redirects to `/login`.
2.  **Login Form:** `login.html` is rendered.
3.  **Submit Credentials:** User enters username/password and submits the form (POST request to `/login`).
4.  **`web_ui.py` Login Route:**
    *   Receives username and password.
    *   Calls `zfs_manager.verify_credentials(username, password)`.
5.  **`ZfsManager` -> Daemon:** Sends a `{'command': 'verify_credentials', 'username': '...', 'password': '...'}` request to the daemon.
6.  **`zfs_daemon.py`:**
    *   Reads the `credentials.json` file (e.g., `/opt/zfdash/data/credentials.json`).
    *   Finds the user entry.
    *   Performs secure password verification (e.g., using `hashlib.pbkdf2_hmac` and comparing against the stored salted hash). **Timing attack resistance is crucial here.**
    *   Sends back `{'success': True}` or `{'success': False, 'error': 'Invalid credentials'}`.
7.  **`ZfsManager` -> `web_ui.py`:** Returns the verification result.
8.  **`web_ui.py` Login Route:**
    *   If successful: Creates a `User` object (from `models.py`), calls `login_user(user)` from Flask-Login (sets session cookie), and redirects to the main page (`/`).
    *   If failed: Re-renders the `login.html` template with an error message.
9.  **Subsequent Requests:** The browser sends the session cookie with future requests. Flask-Login automatically loads the user session, making the user accessible via `current_user` and enforcing `@login_required` decorators.

## 4. Security Considerations

Security is paramount due to the privileged nature of ZFS operations.

### 4.1 Daemon Privileges and Isolation

*   The daemon (`zfs_daemon.py`) runs as root, but its scope is limited. It primarily executes specific `zfs` and `zpool` commands based on structured input from the UI.
*   Input validation within the daemon is important to prevent command injection vulnerabilities, although the primary defense is the structured command format rather than passing raw user strings directly to the shell.

### 4.2 Communication Security

*   Using Polkit for daemon invocation ensures only authorized users can start the privileged process.
*   Using anonymous pipes (`os.pipe()`) for Inter-Process Communication (IPC) prevents other user processes from easily accessing the communication channel. File descriptors are passed directly, avoiding filesystem-based sockets that might have incorrect permissions.

### 4.3 Web UI Security

*   **Authentication:** Flask-Login manages user sessions securely.
*   **Password Hashing:** Passwords are not stored in plaintext. Strong hashing (PBKDF2 with per-user salts) is used via `hashlib`. Comparisons should be timing-attack resistant.
*   **Credential Storage:** `credentials.json` is stored in `/opt/zfdash/data` and should ideally have restrictive permissions (e.g., readable only by root or a dedicated service user, writable only by root for password changes via the daemon). When run as a service (`install_web_service.sh`), a dedicated `zfdash` user runs the web server, but credential verification and changes still go through the root daemon.
*   **CSRF Protection:** Currently, explicit Cross-Site Request Forgery (CSRF) protection (e.g., using Flask-WTF) is **not implemented**. This should be considered for future enhancements to improve security, especially if the Web UI is exposed to less trusted networks.
*   **Secret Key:** A strong, unique `FLASK_SECRET_KEY` is crucial for session security. This is generated during installation (`install.sh`, `install_web_service.sh`) and stored in `/opt/zfdash/data/flask_secret_key.txt` or `/etc/zfdash/web.env`.
*   **HTTPS:** For production deployment over a network, running the Waitress server behind a reverse proxy (like Nginx or Apache) configured for HTTPS is highly recommended.

### 4.4 Polkit Policy

*   **File:** `src/data/policies/org.zfsgui.pkexec.daemon.launch.policy` (installed to `/usr/share/polkit-1/actions/`)
*   **Description:** Defines which users/groups are allowed to execute the `zfs_daemon.py` script via `pkexec`. Typically requires the user to be in an administrative group (like `wheel` or `sudo`) and authenticate. This prevents standard users from launching the root daemon without authorization.

## 5. Installation and Build Process

*   **`build.sh`:** (Run as user) Uses [uv](https://docs.astral.sh/uv/) for fast dependency management and `PyInstaller` to bundle the Python application (`src/`) and its dependencies (from `pyproject.toml`) into a self-contained executable (`dist/zfdash/zfdash`) and copies necessary data files.
*   **`install.sh`:** (Run as root)
    *   Copies the built application from `dist/zfdash` to `/opt/zfdash/app`.
    *   Copies assets (icon, policy file, default credentials) from the source tree (`src/data/`) to appropriate system locations (`/opt/zfdash/data/icons`, `/usr/share/polkit-1/actions`, `/opt/zfdash/data`).
    *   Generates a Flask secret key (`/opt/zfdash/data/flask_secret_key.txt`).
    *   Creates a launcher script (`/usr/local/bin/zfdash`).
    *   Creates a desktop entry (`/usr/share/applications/zfdash.desktop`).
    *   Creates an uninstaller script (`/opt/zfdash/uninstall.sh`).
    *   Sets appropriate permissions.
*   **`install_service/install_web_service.sh`:** (Run as root after `install.sh`)
    *   Creates a dedicated `zfdash` user and group (recommended).
    *   Ensures the user is in necessary groups.
    *   Creates a systemd service file (`/etc/systemd/system/zfdash-web.service`) configured to run the Web UI via `waitress` as the `zfdash` user.
    *   Creates an environment file (`/etc/zfdash/web.env`) for service-specific settings (like `FLASK_SECRET_KEY`, host, port).
    *   Enables and starts the `zfdash-web` service.

## 6. Key Files and Directories

*   **Source Code:** `src/`
*   **Build Output:** `dist/`
*   **Installation Base:** `/opt/zfdash/`
    *   `app/`: Bundled application code.
    *   `data/`: Non-code assets (icons, default `credentials.json`, `flask_secret_key.txt`).
    *   `uninstall.sh`: Uninstaller script.
*   **System Files:**
    *   `/usr/local/bin/zfdash`: Launcher script.
    *   `/usr/share/applications/zfdash.desktop`: Desktop menu entry.
    *   `/usr/share/polkit-1/actions/org.zfsgui.pkexec.daemon.launch.policy`: Polkit policy.
*   **Web Service Files (Method 3):**
    *   `/etc/systemd/system/zfdash-web.service`: Systemd unit file.
    *   `/etc/zfdash/web.env`: Environment variables for the service.
*   **User Configuration:** `~/.config/ZfDash/zfdash.ini`
*   **User Cache:** `~/.cache/ZfDash/`
*   **Daemon Logs:** `/run/user/<UID>/zfdash/daemon.log` (user-specific runtime dir, configurable) or `/tmp/zfdash-daemon.log` (fallback/older versions).

## 7. Development Setup

1.  **Clone Repository:** `git clone https://github.com/ad4mts/zfdash`
2.  **Install uv:** `curl -LsSf https://astral.sh/uv/install.sh | sh`
3.  **Create Virtual Environment:** `uv venv --python 3.11 .venv && source .venv/bin/activate`
4.  **Install Dependencies:** `uv pip install -e .`
5.  **Install Polkit Policy (if not already installed):** `sudo cp src/data/policies/org.zfsgui.pkexec.daemon.launch.policy /usr/share/polkit-1/actions/` (set owner/perms if needed).
6.  **Run:**
    *   **GUI:** `cd src && python3 main.py`
    *   **Web UI (Debug):** `cd src && python3 main.py --web --debug` (Access at `http://127.0.0.1:5001`, uses Flask dev server, default creds `admin:admin`).
    *   **Web UI (Production-like):** `cd src && python3 main.py --web` (Uses Waitress).

Ensure Polkit is configured to allow your user to run the daemon via `pkexec` for manual development runs. The daemon (`zfs_daemon.py`) is launched automatically by `main.py` and does not need to be run separately. 