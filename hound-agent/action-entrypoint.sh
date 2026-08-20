#!/bin/sh
set -eu

out=""
previous=""
for argument in "$@"; do
    if [ "$previous" = "--out" ]; then
        out="$argument"
        break
    fi
    previous="$argument"
done

if [ -n "$out" ] && [ -n "${GITHUB_WORKSPACE:-}" ]; then
    workspace=$(readlink -f "$GITHUB_WORKSPACE")
    output=$(readlink -f "$out")
    case "$output" in
        "$workspace"|"$workspace"/*)
            if [ -e "$output" ] && [ -n "$(find "$output" -mindepth 1 -maxdepth 1 -print -quit 2>/dev/null)" ]; then
                echo "error: action output directory must be empty" >&2
                exit 2
            fi
            mkdir -p "$output"
            chown hound-agent:hound-agent "$output"
            ;;
        *)
            echo "error: action output must be inside GITHUB_WORKSPACE" >&2
            exit 2
            ;;
    esac
fi

# Analyze untrusted repository artifacts without root privileges.
if [ -n "${GITHUB_OUTPUT:-}" ] && [ -e "$GITHUB_OUTPUT" ]; then
    chown hound-agent:hound-agent "$GITHUB_OUTPUT"
fi
exec su -s /bin/sh hound-agent -c 'exec /app/.venv/bin/hound "$@"' -- "$@"
