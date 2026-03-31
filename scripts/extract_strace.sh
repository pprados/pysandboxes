#!/bin/bash
# Script: extract_syscalls_from_app.sh
# Purpose: Traces a program using strace -c and generates a comma-separated
# list of syscalls for Seccomp profiling.
set -euo pipefail

# Check if an application was provided
if [ "$#" -eq 0 ]; then
    echo "Usage: $0 <program_to_run> [arguments...]"
    exit 1
fi

# 1. Create a secure temporary log file
# Using mktemp ensures a unique and safe filename.
TEMP_LOG_FILE=$(mktemp --suffix=.strace)
# Ensure the temporary file is deleted when the script exits (normally or via error)
trap "rm -f $TEMP_LOG_FILE" EXIT

echo "Tracing application: $*"
echo "Temporary log file: $TEMP_LOG_FILE"

# 2. Execute strace
# -c: prints a summary of syscalls
# -f: follows child processes (forks), which is crucial for complex applications
# -o: redirects all output (including the summary) to the temporary file
strace -cfo "$TEMP_LOG_FILE" "$@"

# Check for strace or program execution errors
if [ $? -ne 0 ]; then
    echo "Error executing strace or the target program." >&2
    exit 2
fi

# 3. Extract and format the syscall list
# Pipeline breakdown:
# a. tail -n +3 : Skip the initial two header lines.
# b. grep -v 'total' : Remove the summary line.
# c. grep -v '------' : Remove the table separator lines.
# d. awk '{print $NF}' : Isolate the last field (the syscall name).
# e. tr '\n' ',' : Replace newlines with commas.
# f. sed 's/,$//' : Remove the trailing comma from the end of the string.
SYSCALL_LIST=$(cat "$TEMP_LOG_FILE" | \
               tail -n +3 | \
               grep -v 'total' | \
               grep -v -- '------' | \
               awk '{print $NF}' | \
               tr '\n' ',' | \
               sed 's/,$//')

# 4. Display the result
echo ""
echo "--- Generated Syscall List for Seccomp ---"
echo "$SYSCALL_LIST"

exit 0
