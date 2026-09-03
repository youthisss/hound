#!/bin/sh
set -eu

out=""
log=""
repo=""
previous=""
for argument in "$@"; do
    case "$argument" in
        --output-dir=*|--out=*) out="${argument#*=}" ;;
        --log=*) log="${argument#*=}" ;;
        --repo-dir=*|--repo=*) repo="${argument#*=}" ;;
    esac
    case "$previous" in
        --output-dir|--out) out="$argument" ;;
        --log) log="$argument" ;;
        --repo-dir|--repo) repo="$argument" ;;
    esac
    previous="$argument"
done

if [ -n "${GITHUB_WORKSPACE:-}" ]; then
    workspace=$(readlink -f "$GITHUB_WORKSPACE")
    if [ ! -d "$workspace" ]; then
        echo "error: GITHUB_WORKSPACE must be an existing directory" >&2
        exit 2
    fi
    workspace_uid=$(stat -c '%u' "$workspace")
    workspace_gid=$(stat -c '%g' "$workspace")

    resolve_workspace_path() {
        case "$1" in
            /*) readlink -f "$1" ;;
            *) readlink -f "$workspace/$1" ;;
        esac
    }

    require_workspace_path() {
        case "$1" in
            "$workspace"|"$workspace"/*) ;;
            *) echo "error: action $2 must be inside GITHUB_WORKSPACE" >&2; exit 2 ;;
        esac
    }

    if [ -z "$log" ]; then
        echo "error: action log path is required" >&2
        exit 2
    fi
    log_path=$(resolve_workspace_path "$log")
    require_workspace_path "$log_path" "log"
    if [ ! -f "$log_path" ]; then
        echo "error: action log must be an existing regular file" >&2
        exit 2
    fi

    cd "$workspace"

    if [ -n "$repo" ]; then
        repo_path=$(resolve_workspace_path "$repo")
        require_workspace_path "$repo_path" "repo"
        if [ ! -d "$repo_path" ]; then
            echo "error: action repo must be an existing directory" >&2
            exit 2
        fi
    fi

    if [ -n "$out" ]; then
        output=$(resolve_workspace_path "$out")
        require_workspace_path "$output" "output"
        case "$output" in
        "$workspace"|"$workspace"/*)
            if [ -e "$output" ] && [ -n "$(find "$output" -mindepth 1 -maxdepth 1 -print -quit 2>/dev/null)" ]; then
                echo "error: action output directory must be empty" >&2
                exit 2
            fi
            mkdir -p "$output"
            chown hound:hound "$output"
            ;;
        esac
    fi
fi

# Analyze untrusted repository artifacts without root privileges.
if [ -n "${GITHUB_OUTPUT:-}" ]; then
    touch "$GITHUB_OUTPUT"
    github_output_uid=$(stat -c '%u' "$GITHUB_OUTPUT")
    github_output_gid=$(stat -c '%g' "$GITHUB_OUTPUT")
    chown hound:hound "$GITHUB_OUTPUT"
fi
export GITHUB_WORKSPACE="${GITHUB_WORKSPACE:-}"
export GITHUB_OUTPUT="${GITHUB_OUTPUT:-}"
export HOME=/home/hound
export XDG_CONFIG_HOME=/home/hound/.config
export XDG_CACHE_HOME=/home/hound/.cache
set +e
su -m -s /bin/sh -c 'cd "$GITHUB_WORKSPACE" && exec /app/.venv/bin/hound "$@"' -- hound action-entrypoint "$@"
status=$?
set -e

# Return generated artifacts to the host runner without making them world-readable.
if [ -n "${output:-}" ]; then
    chown -R "$workspace_uid:$workspace_gid" "$output"
fi
if [ -n "${GITHUB_OUTPUT:-}" ]; then
    chown "$github_output_uid:$github_output_gid" "$GITHUB_OUTPUT"
fi
exit "$status"
