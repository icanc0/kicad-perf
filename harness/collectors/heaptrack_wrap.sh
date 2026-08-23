#!/bin/bash
# heaptrack_wrap — run a command under heaptrack, parse the summary out.
#
# Usage: heaptrack_wrap <output_dir> -- <command> [args...]
#
# On exit, writes:
#   <output_dir>/heaptrack.gz         raw capture
#   <output_dir>/heaptrack.summary.txt heaptrack_print --output
#   <output_dir>/heaptrack.summary.json  extracted top-line stats
#
# The JSON is what the runner slots into the report.

set -euo pipefail

OUT="$1"; shift
[ "$1" = "--" ] || { echo "usage: $0 <output_dir> -- <cmd> [args]" >&2; exit 2; }
shift

mkdir -p "$OUT"

# heaptrack + heaptrack_print in ~/local/wx-root
export PATH="$HOME/local/wx-root/usr/bin:$PATH"

# Run — heaptrack writes ${OUT}/heaptrack.<basename>.<pid>.gz by default;
# override with -o for a fixed name.
heaptrack -o "$OUT/heaptrack" "$@" >"$OUT/stdout.log" 2>"$OUT/stderr.log" || true

# Locate the produced capture — heaptrack sometimes tacks on .gz vs .zst.
GZ=""
for pat in heaptrack.gz "heaptrack.*.gz" "heaptrack.*.zst"; do
    for f in "$OUT"/$pat; do
        [ -f "$f" ] && GZ="$f" && break 2
    done
done
[ -z "$GZ" ] && { echo "no heaptrack capture" >&2; exit 3; }

heaptrack_print "$GZ" > "$OUT/heaptrack.summary.txt" 2>&1

# Parse the trailer:
#   total runtime: 3.71s.
#   calls to allocation functions: 447223 (120642/s)
#   temporary memory allocations: 6888 (1858/s)
#   peak heap memory consumption: 6.81M
#   peak RSS (including heaptrack overhead): 61.30M
#   total memory leaked: 695.69K
awk '
    /total runtime:/                            { runtime = $3 }
    /calls to allocation functions:/            { alloc = $5 }
    /temporary memory allocations:/             { temp = $4 }
    /peak heap memory consumption:/             { peak_heap = $5 }
    /peak RSS \(including heaptrack overhead\):/{ peak_rss = $6 }
    /total memory leaked:/                      { leaked = $4 }
    END {
        printf("{\n")
        printf("  \"runtime\": \"%s\",\n",        runtime)
        printf("  \"allocations\": %s,\n",         alloc  ? alloc  : 0)
        printf("  \"temporary_allocations\": %s,\n", temp ? temp   : 0)
        printf("  \"peak_heap\": \"%s\",\n",       peak_heap)
        printf("  \"peak_rss\": \"%s\",\n",        peak_rss)
        printf("  \"leaked\": \"%s\"\n",           leaked)
        printf("}\n")
    }' "$OUT/heaptrack.summary.txt" > "$OUT/heaptrack.summary.json"

cat "$OUT/heaptrack.summary.json"
