#!/bin/bash
# ZfDash Docker Entrypoint
# Syncs container's /etc/hostid with host system to prevent ZFS hostid mismatches

echo "HostID: Checking host system configuration..."

# Check if /host-etc is accessible
if [ ! -d /host-etc ]; then
    echo "HostID: Warning - /host-etc not accessible, continuing without sync"
    exec "$@"
fi

# Sync hostid with host system
if [ -f /host-etc/hostid ]; then
    echo "HostID: Syncing from host /etc/hostid"
    cp /host-etc/hostid /etc/hostid
else
    echo "HostID: No host /etc/hostid found, ensuring container has no hostid"
    rm -f /etc/hostid
fi

echo "HostID: Configuration complete, starting application..."
exec "$@"
