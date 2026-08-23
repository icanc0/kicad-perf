/*
 * rss_sampler — spawn a child, poll /proc/<pid>/statm at 50 Hz,
 *               write time-series CSV, print summary from wait4 rusage.
 *
 * Usage:
 *   rss_sampler <output.csv> -- <command> [args...]
 *
 * Output CSV columns:
 *   t_ms,vm_size_kb,vm_rss_kb,vm_shared_kb,vm_text_kb,vm_data_kb
 * plus a final line:
 *   SUMMARY,exit=<int>,wall_ms=<int>,user_ms=<int>,sys_ms=<int>,max_rss_kb=<int>
 *
 * Build:  cc -O2 -Wall -o rss_sampler rss_sampler.c
 */

#define _POSIX_C_SOURCE 200809L
#include <errno.h>
#include <fcntl.h>
#include <inttypes.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/resource.h>
#include <sys/time.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

/* Poll interval in nanoseconds — 20 ms == 50 Hz. */
static const long POLL_NS = 20L * 1000L * 1000L;

/* Kernel page size cached at startup. */
static long g_page_kb = 4;

/* Monotonic ms since sampler start. Signed arithmetic so a negative
 * tv_nsec delta borrows from the tv_sec delta correctly. */
static int64_t now_ms(struct timespec *base) {
    struct timespec t;
    clock_gettime(CLOCK_MONOTONIC, &t);
    int64_t sec_d  = (int64_t)t.tv_sec  - (int64_t)base->tv_sec;
    int64_t nsec_d = (int64_t)t.tv_nsec - (int64_t)base->tv_nsec;
    return sec_d * 1000LL + nsec_d / 1000000LL;
}

/* Read /proc/<pid>/statm, return 0 on success (line filled), -1 on gone. */
static int read_statm(int pid, uint64_t *out_size, uint64_t *out_rss,
                      uint64_t *out_share, uint64_t *out_text,
                      uint64_t *out_data) {
    char path[64];
    snprintf(path, sizeof path, "/proc/%d/statm", pid);
    FILE *f = fopen(path, "r");
    if (!f) return -1;

    /* statm columns (in pages): size resident shared text lib data dt */
    unsigned long size, resident, share, text, lib, data, dt;
    int n = fscanf(f, "%lu %lu %lu %lu %lu %lu %lu",
                   &size, &resident, &share, &text, &lib, &data, &dt);
    fclose(f);
    if (n < 6) return -1;

    *out_size  = (uint64_t)size     * (uint64_t)g_page_kb;
    *out_rss   = (uint64_t)resident * (uint64_t)g_page_kb;
    *out_share = (uint64_t)share    * (uint64_t)g_page_kb;
    *out_text  = (uint64_t)text     * (uint64_t)g_page_kb;
    *out_data  = (uint64_t)data     * (uint64_t)g_page_kb;
    return 0;
}

static void die(const char *msg) {
    fprintf(stderr, "rss_sampler: %s: %s\n", msg, strerror(errno));
    exit(2);
}

int main(int argc, char **argv) {
    if (argc < 4 || strcmp(argv[2], "--") != 0) {
        fprintf(stderr, "usage: %s <output.csv> -- <command> [args...]\n", argv[0]);
        return 2;
    }
    const char *out_path = argv[1];
    char **child_argv = &argv[3];

    long pgsz = sysconf(_SC_PAGESIZE);
    if (pgsz > 0) g_page_kb = pgsz / 1024;

    FILE *out = fopen(out_path, "w");
    if (!out) die("open output");
    fprintf(out, "t_ms,vm_size_kb,vm_rss_kb,vm_shared_kb,vm_text_kb,vm_data_kb\n");

    pid_t pid = fork();
    if (pid < 0) die("fork");
    if (pid == 0) {
        /* Child. Exec directly. */
        execvp(child_argv[0], child_argv);
        fprintf(stderr, "rss_sampler: exec %s: %s\n", child_argv[0], strerror(errno));
        _exit(127);
    }

    /* Parent: poll until child exits. */
    struct timespec base;
    clock_gettime(CLOCK_MONOTONIC, &base);
    struct timespec sleep_ts = { .tv_sec = 0, .tv_nsec = POLL_NS };

    for (;;) {
        int status;
        pid_t r = waitpid(pid, &status, WNOHANG);
        if (r == pid) {
            /* Child exited — one last statm read likely fails, but try. */
            uint64_t size = 0, rss = 0, share = 0, text = 0, data = 0;
            if (read_statm(pid, &size, &rss, &share, &text, &data) == 0) {
                fprintf(out, "%" PRId64 ",%" PRIu64 ",%" PRIu64 ",%" PRIu64 ",%" PRIu64 ",%" PRIu64 "\n",
                        now_ms(&base), size, rss, share, text, data);
            }

            /* rusage isn't returned by waitpid — call wait4 with WNOHANG on
             * a bogus pid to grab our own accumulated child rusage. Simpler:
             * use getrusage(RUSAGE_CHILDREN) which now includes this child. */
            struct rusage ru;
            getrusage(RUSAGE_CHILDREN, &ru);

            int exit_code = -1;
            if (WIFEXITED(status)) exit_code = WEXITSTATUS(status);
            else if (WIFSIGNALED(status)) exit_code = 128 + WTERMSIG(status);

            fprintf(out,
                    "SUMMARY,exit=%d,wall_ms=%" PRId64 ",user_ms=%ld,sys_ms=%ld,max_rss_kb=%ld\n",
                    exit_code, now_ms(&base),
                    (long)(ru.ru_utime.tv_sec * 1000 + ru.ru_utime.tv_usec / 1000),
                    (long)(ru.ru_stime.tv_sec * 1000 + ru.ru_stime.tv_usec / 1000),
                    (long)ru.ru_maxrss);
            fclose(out);
            return exit_code;
        }
        if (r < 0 && errno != EINTR) die("waitpid");

        uint64_t size = 0, rss = 0, share = 0, text = 0, data = 0;
        if (read_statm(pid, &size, &rss, &share, &text, &data) == 0) {
            fprintf(out, "%" PRIu64 ",%" PRIu64 ",%" PRIu64 ",%" PRIu64 ",%" PRIu64 ",%" PRIu64 "\n",
                    now_ms(&base), size, rss, share, text, data);
        }

        nanosleep(&sleep_ts, NULL);
    }
}
