#!/bin/bash
# set_ip_env.sh : Patches or adds the MY_IP variable in a specified file with the current IP address.
# Usage : ./set_ip_env.sh path/to/your/config_file
# This script can be used in the pre-launch of a run configuration within a development environment.

set -euo pipefail

# Check if a filename was provided as an argument
if [ -z "$1" ]; then
    echo "Error: Please provide the path to the file to patch as a parameter."
    echo "Usage: $0 <FILE>"
    exit 1
fi

FILE_TO_PATCH="$1"

# Check if the file exists
if [ ! -f "$FILE_TO_PATCH" ]; then
    echo "Error: File not found at location: $FILE_TO_PATCH"
    exit 1
fi

# 1. Extract the current IP
# Get the first listed IP address from 'hostname -I' (suitable for Ubuntu/Linux)
CURRENT_IP=$(hostname -I | awk '{print $1}')

if [ -z "$CURRENT_IP" ]; then
    echo "Warning: Unable to get the current IP address. Exiting without modification."
    exit 1
fi

# Define the line to be inserted/patched
NEW_LINE="MY_IP=${CURRENT_IP}"

# 2. Patching or Appending

# Use grep to check if the variable MY_IP= is already present in the file
if grep -q "^MY_IP=" "$FILE_TO_PATCH"; then

    # Case 1: The variable exists (MY_IP=...)
    echo "Updating the MY_IP variable in $FILE_TO_PATCH with IP: $CURRENT_IP"

    # Use sed to replace the existing line starting with MY_IP=
    # -i.bak: Edits the file in place and creates a backup file (.bak)
    # The | separator is used instead of / to avoid issues with dots in the IP address.
    sed -i.bak "s|^MY_IP=.*|$NEW_LINE|" "$FILE_TO_PATCH"

else
    # Case 2: The variable does not exist, append it to the end of the file
    echo "Appending the MY_IP variable to the end of $FILE_TO_PATCH with IP: $CURRENT_IP"

    # Append the new line to the file
    echo "$NEW_LINE" >> "$FILE_TO_PATCH"
fi

# Remove the backup file created by sed (-i.bak)
if [ -f "$FILE_TO_PATCH.bak" ]; then
    rm "$FILE_TO_PATCH.bak"
fi

echo "Operation complete."