#!/bin/bash

echo "--- ZfDash Enhanced Environment Check (GUI & Web UI) ---"
echo ""

# --- Find Python First ---
PYTHON_EXEC=""
# Prefer python3 if available
if command -v python3 &> /dev/null; then
    PYTHON_EXEC=$(command -v python3)
# If not, check if 'python' exists and is Python 3
elif command -v python &> /dev/null; then
    if python --version 2>&1 | grep -q "Python 3"; then
        PYTHON_EXEC=$(command -v python)
    fi
fi

# --- Helper function to print status ---
# Takes status (OK, WARN, FAIL, INFO), message, and optional version string
print_status() {
    local status=$1
    local message=$2
    local version_info=""
    # Check if a third argument (version) is provided
    if [ -n "$3" ]; then
        version_info=" (Version: $3)"
    fi

    local prefix="[INFO]" # Default prefix
    local color_start="\033[0;34m" # Blue for INFO
    local color_end="\033[0m"

    if [ "$status" == "OK" ]; then
        prefix="[ OK ]"
        color_start="\033[0;32m" # Green
    elif [ "$status" == "WARN" ]; then
        prefix="[WARN]"
        color_start="\033[0;33m" # Yellow
    elif [ "$status" == "FAIL" ]; then
        prefix="[FAIL]"
        color_start="\033[0;31m" # Red
    fi
    # Use printf for safer formatting and color handling
    printf "    %b%s%b %s%s\n" "$color_start" "$prefix" "$color_end" "$message" "$version_info"
}

# --- Helper function to get pip package version ---
# Takes pip executable path and package name
get_pip_package_version() {
    local pip_cmd="$1"
    local package_name="$2"
    local version=""
    if [ -n "$pip_cmd" ]; then
        # Use grep and cut to extract version, handle errors gracefully
        version=$($pip_cmd show "$package_name" 2>/dev/null | grep '^Version:' | cut -d' ' -f2)
    fi
    echo "$version" # Return the version string (empty if not found/error)
}


# --- System Information ---
echo "** 1. Operating System:"
if [ -f /etc/os-release ]; then
    PRETTY_NAME=$(grep PRETTY_NAME /etc/os-release | cut -d= -f2 | tr -d '"')
    print_status "INFO" "$PRETTY_NAME"
else
    print_status "WARN" "Could not determine OS from /etc/os-release"
fi
echo ""

echo "** 2. Kernel Version:"
KERNEL_VER=$(uname -r)
if [ -n "$KERNEL_VER" ]; then
    print_status "INFO" "Kernel: $KERNEL_VER"
else
    print_status "WARN" "Could not determine kernel version"
fi
echo ""

# --- ZFS Checks (Mandatory) ---
echo "** 3. ZFS Setup (Mandatory):"
ZPOOL_FOUND=false
ZFS_FOUND=false
ZFS_MODULE_OK=false
ZFS_VERSION=""
if command -v zpool &> /dev/null; then
    ZPOOL_PATH=$(command -v zpool)
    # Attempt to get version - zpool version often shows zfs version
    ZFS_VERSION=$(zpool --version 2>/dev/null | grep -i zfs | head -n 1 | sed -e 's/zfs-//' -e 's/zfs_//' | awk '{print $NF}')
    print_status "OK" "zpool command found: $ZPOOL_PATH" "$ZFS_VERSION"
    # Display full version output if available
    if [ -n "$ZFS_VERSION" ]; then
        echo "    Full ZFS Version Output:"
        zpool --version | sed 's/^/      /' # Indent output
    fi
    ZPOOL_FOUND=true
else
    print_status "FAIL" "zpool command not found (required)"
fi

if command -v zfs &> /dev/null; then
    ZFS_PATH=$(command -v zfs)
    # Don't repeat version if already found via zpool
    if [ -z "$ZFS_VERSION" ]; then
        # Try getting version from zfs command if zpool failed
        ZFS_VERSION=$(zfs --version 2>/dev/null | grep -i zfs | head -n 1 | sed -e 's/zfs-//' -e 's/zfs_//' | awk '{print $NF}')
        print_status "OK" "zfs command found: $ZFS_PATH" "$ZFS_VERSION"
    else
        print_status "OK" "zfs command found: $ZFS_PATH" "(Version checked via zpool)"
    fi
    ZFS_FOUND=true
else
    print_status "FAIL" "zfs command not found (required)"
fi

# Check if module is loaded or built-in
if lsmod | grep -i '^zfs ' > /dev/null; then
    print_status "OK" "ZFS kernel module appears loaded via lsmod"
    ZFS_MODULE_OK=true
elif grep -q -w zfs /proc/filesystems; then
    print_status "OK" "ZFS filesystem type found in /proc/filesystems (likely built-in)"
    ZFS_MODULE_OK=true
else
    print_status "FAIL" "ZFS kernel module does not appear loaded or built-in (Check 'modprobe zfs' or kernel config)"
fi

# Check packages (optional informative)
echo "  Package Info (Informative):"
if command -v dpkg &> /dev/null; then
    dpkg -s zfsutils-linux 2>/dev/null | grep -E '^Package|^Version|^Status' | sed 's/^/    /' || print_status "INFO" "zfsutils-linux package status not found via dpkg"
elif command -v rpm &> /dev/null; then
    rpm -qi zfs 2>/dev/null | grep -E '^(Name|Version|Release|Architecture)' | sed 's/^/    /' || print_status "INFO" "zfs package status not found via rpm"
else
    print_status "INFO" "dpkg/rpm not found to check ZFS package"
fi
echo ""

# --- Python & Core Dependencies (Mandatory) ---
echo "** 4. Python Setup (Mandatory):"
PIP_EXEC=""
PYTHON_OK=false
PIP_OK=false
PYTHON_VER=""
PIP_VER_SHORT=""
if [ -n "$PYTHON_EXEC" ]; then
    PYTHON_VER=$("$PYTHON_EXEC" --version 2>&1) # Get full version string
    print_status "OK" "Python 3 found: $PYTHON_EXEC" "$PYTHON_VER"
    PYTHON_OK=true
    # Check if pip is available for this Python
    if "$PYTHON_EXEC" -m pip --version &> /dev/null; then
        PIP_EXEC="$PYTHON_EXEC -m pip"
        PIP_VER_FULL=$($PIP_EXEC --version 2>&1) # Get full version string
        PIP_VER_SHORT=$(echo "$PIP_VER_FULL" | cut -d' ' -f2) # Extract just the number
        print_status "OK" "pip found for this Python" "$PIP_VER_FULL"
        PIP_OK=true
    else
        print_status "WARN" "pip module not found for $PYTHON_EXEC (needed for dependency checks/install)"
    fi
else
    print_status "FAIL" "Python 3 interpreter not found in PATH (python3 or python)"
fi
echo ""

echo "** 5. Required Python Modules (using '$PIP_EXEC'):"
FLASK_OK=false
PYSIDE6_FOUND=false
WAITRESS_FOUND=false
if [ "$PIP_OK" = true ]; then
    # Check Flask (for Web UI)
    FLASK_VER=$(get_pip_package_version "$PIP_EXEC" "Flask")
    if [ -n "$FLASK_VER" ]; then
        print_status "OK" "Flask found" "$FLASK_VER"
        FLASK_OK=true
    else
        print_status "FAIL" "Flask not found (Required for Web UI)"
    fi

    # Check Waitress (Alternative Web Server)
    WAITRESS_VER=$(get_pip_package_version "$PIP_EXEC" "waitress")
    if [ -n "$WAITRESS_VER" ]; then
        print_status "OK" "Waitress found" "$WAITRESS_VER"
        WAITRESS_FOUND=true
    else
        print_status "INFO" "Waitress not found (Optional WSGI Server)"
    fi

    # Check PySide6 (for GUI - check anyway for info)
    PYSIDE6_VER=$(get_pip_package_version "$PIP_EXEC" "PySide6")
    if [ -n "$PYSIDE6_VER" ]; then
        print_status "OK" "PySide6 found (Needed for GUI only)" "$PYSIDE6_VER"
        PYSIDE6_FOUND=true
    else
        print_status "INFO" "PySide6 not found (Only needed for GUI)"
    fi
    echo "    (Note: If using install.sh, check versions inside the script's venv)"

else
    print_status "FAIL" "Cannot check Python modules - pip not found"
fi
echo ""

echo "** 6. Python venv Module:"
VENV_OK=false
if [ "$PYTHON_OK" = true ]; then
  if "$PYTHON_EXEC" -m venv --help &> /dev/null; then
    print_status "OK" "venv module appears available via '$PYTHON_EXEC -m venv'"
    VENV_OK=true
  else
    print_status "FAIL" "venv module NOT found for $PYTHON_EXEC (Required by install.sh)"
  fi
else
    print_status "FAIL" "Cannot check venv - Python 3 not found"
fi
echo ""


# --- Utility Dependencies (Mandatory) ---
echo "** 7. lsblk (Mandatory):"
LSBLK_PATH=$(command -v lsblk)
LSBLK_JSON_OK=false
LSBLK_VER=""
if [ -n "$LSBLK_PATH" ]; then
    LSBLK_VER=$($LSBLK_PATH --version 2>/dev/null | head -n 1 | sed 's/lsblk from //') # Try to clean up output
    print_status "OK" "lsblk found: $LSBLK_PATH" "$LSBLK_VER"
    # Check JSON output capability
    if lsblk -Jpbn -o PATH --nodeps > /dev/null 2>&1 && [[ "$(lsblk -Jpbn -o PATH --nodeps 2>/dev/null | head -c 1)" == "{" ]]; then
        print_status "OK" "lsblk JSON output (-J) seems supported (Required)"
        LSBLK_JSON_OK=true
    else
        print_status "FAIL" "lsblk JSON output (-J) might NOT be supported or produced an error (Required)"
    fi
else
     print_status "FAIL" "lsblk command not found (Required)"
fi
echo ""

# --- GUI Specific Dependencies (Informative/Warn) ---
echo "** 8. Polkit (PolicyKit):"
POLKIT_VER=""
POLKIT_FOUND=false
# Try getting package version first
if command -v dpkg &> /dev/null; then
    POLKIT_VER=$(dpkg -s policykit-1 2>/dev/null | grep '^Version:' | cut -d' ' -f2)
elif command -v rpm &> /dev/null; then
    POLKIT_VER=$(rpm -q --qf '%{VERSION}' polkit 2>/dev/null)
fi
# Fallback: Check pkcheck command version if package not found
if [ -z "$POLKIT_VER" ] && command -v pkcheck &> /dev/null; then
    POLKIT_VER=$(pkcheck --version 2>/dev/null | awk '{print $NF}') # Attempt to get version from pkcheck
fi

if [ -n "$POLKIT_VER" ]; then
    print_status "OK" "Polkit found (Needed for GUI authentication)" "$POLKIT_VER"
    POLKIT_FOUND=true
else
    print_status "WARN" "Could not determine Polkit version (Needed for GUI authentication)"
fi
echo ""

echo "** 9. pkexec:"
PKEXEC_PATH=$(command -v pkexec)
PKEXEC_FOUND=false
PKEXEC_VER=""
if [ -n "$PKEXEC_PATH" ]; then
    # pkexec version usually matches polkit, but try anyway
    PKEXEC_VER=$(pkexec --version 2>/dev/null | awk '{print $NF}')
    if [ -n "$PKEXEC_VER" ]; then
        print_status "OK" "pkexec found: $PKEXEC_PATH" "$PKEXEC_VER (Needed for GUI authentication)"
    else
        # If version command fails, still report found status
        print_status "OK" "pkexec found: $PKEXEC_PATH (Needed for GUI authentication)" "(Version check failed)"
    fi
    PKEXEC_FOUND=true
else
    print_status "WARN" "pkexec not found in PATH (Needed for GUI authentication)"
fi
echo ""

# --- Deployment Considerations (Informative) ---
echo "** 10. Web Server Deployment (Informative):"
print_status "INFO" "For headless/server deployment, DO NOT use 'flask run' or 'app.run()'."
print_status "INFO" "Use a production WSGI server (e.g., Gunicorn, uWSGI, Waitress)."
print_status "INFO" "A reverse proxy (e.g., Nginx, Apache) is highly recommended."
# Check if common WSGI servers are installed (optional) and get versions
if command -v gunicorn &> /dev/null; then
    GUNICORN_VER=$(gunicorn --version 2>/dev/null | awk '{print $NF}')
    print_status "INFO" "gunicorn found: $(command -v gunicorn)" "$GUNICORN_VER"
fi
if command -v uwsgi &> /dev/null; then
    UWSGI_VER=$(uwsgi --version 2>/dev/null)
    print_status "INFO" "uwsgi found: $(command -v uwsgi)" "$UWSGI_VER"
fi
# Waitress version checked via pip in section 5, just check command existence here
if command -v waitress-serve &> /dev/null; then
    if [ "$WAITRESS_FOUND" = true ]; then
         print_status "INFO" "waitress-serve command found: $(command -v waitress-serve)" "(Version: $WAITRESS_VER - via pip)"
    else
         print_status "INFO" "waitress-serve command found: $(command -v waitress-serve)" "(Python package not detected via pip)"
    fi
fi
echo ""

echo "** 11. Daemon Management (Informative):"
print_status "INFO" "The zfs_daemon.py needs to run as root."
print_status "INFO" "Use a process manager (like systemd) to manage the daemon service."
print_status "INFO" "Ensure correct permissions on the daemon socket (e.g., /run/zfdash/daemon.sock)."
print_status "INFO" "The user running the Web UI (e.g., www-data) must have access to the daemon socket."
echo ""


# --- Desktop Environment / Session Info (Informative) ---
echo "** 12. Desktop Environment (Informative):"
print_status "INFO" "XDG_CURRENT_DESKTOP=${XDG_CURRENT_DESKTOP:-Not Set}"
print_status "INFO" "DESKTOP_SESSION=${DESKTOP_SESSION:-Not Set}"
echo ""

echo "** 13. Display Server (Informative):"
print_status "INFO" "XDG_SESSION_TYPE=${XDG_SESSION_TYPE:-Not Set}"
print_status "INFO" "WAYLAND_DISPLAY=${WAYLAND_DISPLAY:-Not Set}"
print_status "INFO" "DISPLAY=${DISPLAY:-Not Set}"
echo ""


echo "--- Check Summary ---"
# Check mandatory components for *core functionality* (Daemon + Base CLI interaction)
CORE_OK=true
if [ "$PYTHON_OK" != true ]; then CORE_OK=false; fi
if [ "$ZPOOL_FOUND" != true ]; then CORE_OK=false; fi
if [ "$ZFS_FOUND" != true ]; then CORE_OK=false; fi
if [ "$ZFS_MODULE_OK" != true ]; then CORE_OK=false; fi
if [ "$LSBLK_JSON_OK" != true ]; then CORE_OK=false; fi

# Check specific components
WEBUI_OK=true
if [ "$FLASK_OK" != true ]; then WEBUI_OK=false; fi
# Consider if Waitress should be mandatory if Flask is? For now, keep optional.

INSTALL_OK=true
if [ "$VENV_OK" != true ]; then INSTALL_OK=false; fi

GUI_OK=true
if [ "$POLKIT_FOUND" != true ]; then GUI_OK=false; fi
if [ "$PKEXEC_FOUND" != true ]; then GUI_OK=false; fi
if [ "$PYSIDE6_FOUND" != true ]; then GUI_OK=false; fi # Added PySide6 check here

FINAL_EXIT_CODE=0
echo ""
if [ "$CORE_OK" = true ]; then
    print_status "OK" "Core mandatory checks passed (Python3, ZFS tools/module, lsblk+JSON)."
else
    print_status "FAIL" "One or more core mandatory checks failed! See details above."
    FINAL_EXIT_CODE=1
fi

if [ "$WEBUI_OK" = true ]; then
    print_status "OK" "Web UI specific checks passed (Flask)."
else
    print_status "FAIL" "Web UI specific checks failed (Flask)! Web UI will not function."
    FINAL_EXIT_CODE=1 # Make Flask mandatory for overall success
fi

if [ "$INSTALL_OK" = true ]; then
    print_status "OK" "Checks for install script passed (venv)."
else
    print_status "FAIL" "Checks for install script failed (venv)! install.sh may fail."
    # Don't fail overall check just for venv
fi

if [ "$GUI_OK" = true ]; then
    print_status "OK" "GUI specific checks passed (Polkit, pkexec, PySide6)."
else
    print_status "WARN" "One or more GUI specific checks failed (Polkit, pkexec, PySide6)! GUI may not work correctly or at all."
fi
echo ""
echo "--- Check Complete ---"

exit $FINAL_EXIT_CODE
