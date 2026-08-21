/*
 * Standalone test server that speaks the same wire protocol as
 * kicad/cli/command_daemon.cpp — but doesn't need any of kicad's deps.
 * Used to confirm that the request parser + response writer are correct
 * before landing them in the real daemon.
 *
 * Build:  gcc -O2 -Wall -Wextra -o wire_protocol_test_server \
 *              wire_protocol_test_server.c
 *
 * Use:    ./wire_protocol_test_server /tmp/wire_test.sock
 *
 * Then from another shell:
 *   python3 kicad_cli_daemon_client.py --socket /tmp/wire_test.sock \
 *                                       -- pcb export svg board.kicad_pcb
 */

#include <errno.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <sys/un.h>
#include <unistd.h>

#define REQ_MAGIC  0x4B434C49u  /* "KCLI" */
#define RESP_MAGIC 0x53544154u  /* "STAT" */

static volatile sig_atomic_t g_stop = 0;

static void on_signal(int sig) { (void) sig; g_stop = 1; }

static uint32_t read_u32_be(const unsigned char* p) {
    return ((uint32_t) p[0] << 24) | ((uint32_t) p[1] << 16)
           | ((uint32_t) p[2] << 8) | (uint32_t) p[3];
}

static void write_u32_be(unsigned char* p, uint32_t v) {
    p[0] = (v >> 24) & 0xff;
    p[1] = (v >> 16) & 0xff;
    p[2] = (v >> 8) & 0xff;
    p[3] = v & 0xff;
}

static int recv_all(int fd, void* buf, size_t len) {
    char* p = buf;
    size_t got = 0;
    while (got < len) {
        ssize_t n = recv(fd, p + got, len - got, 0);
        if (n == 0) return -1;
        if (n < 0) { if (errno == EINTR) continue; return -1; }
        got += (size_t) n;
    }
    return 0;
}

static int send_all(int fd, const void* buf, size_t len) {
    const char* p = buf;
    size_t sent = 0;
    while (sent < len) {
        ssize_t n = send(fd, p + sent, len - sent, MSG_NOSIGNAL);
        if (n < 0) { if (errno == EINTR) continue; return -1; }
        sent += (size_t) n;
    }
    return 0;
}

static void handle_client(int cfd) {
    unsigned char hdr[8];
    if (recv_all(cfd, hdr, 8) < 0) { close(cfd); return; }

    uint32_t magic = read_u32_be(hdr);
    uint32_t argc  = read_u32_be(hdr + 4);

    if (magic != REQ_MAGIC || argc > 4096) {
        fprintf(stderr, "bad request magic=%08x argc=%u\n", magic, argc);
        close(cfd);
        return;
    }

    /* Build a "stdout capture" of the argv+cwd, same as the C++ stub. */
    char out[8192];
    size_t out_len = 0;

    for (uint32_t i = 0; i < argc; ++i) {
        unsigned char lb[4];
        if (recv_all(cfd, lb, 4) < 0) { close(cfd); return; }
        uint32_t len = read_u32_be(lb);
        if (len > 4096) { close(cfd); return; }

        char arg[4096];
        if (len > 0 && recv_all(cfd, arg, len) < 0) { close(cfd); return; }

        int n = snprintf(out + out_len, sizeof(out) - out_len,
                         "argv[%u]=%.*s\n", (unsigned) i, (int) len, arg);
        if (n > 0 && out_len + (size_t) n < sizeof(out))
            out_len += (size_t) n;
    }

    unsigned char cwdlb[4];
    if (recv_all(cfd, cwdlb, 4) < 0) { close(cfd); return; }
    uint32_t cwd_len = read_u32_be(cwdlb);
    char cwd[4096];
    if (cwd_len > 0 && recv_all(cfd, cwd, cwd_len) < 0) { close(cfd); return; }

    int n = snprintf(out + out_len, sizeof(out) - out_len,
                     "cwd=%.*s\n", (int) cwd_len, cwd);
    if (n > 0 && out_len + (size_t) n < sizeof(out)) out_len += (size_t) n;

    /* Response */
    unsigned char h0[12];
    write_u32_be(h0 + 0, RESP_MAGIC);
    write_u32_be(h0 + 4, 0u); /* exit=0 */
    write_u32_be(h0 + 8, (uint32_t) out_len);
    if (send_all(cfd, h0, 12) < 0) { close(cfd); return; }
    if (out_len && send_all(cfd, out, out_len) < 0) { close(cfd); return; }
    unsigned char h1[4];
    write_u32_be(h1, 0u); /* stderr_len=0 */
    send_all(cfd, h1, 4);
    close(cfd);
}

int main(int argc, char** argv) {
    if (argc != 2) { fprintf(stderr, "usage: %s SOCKET_PATH\n", argv[0]); return 1; }
    const char* path = argv[1];

    unlink(path);

    int lfd = socket(AF_UNIX, SOCK_STREAM | SOCK_CLOEXEC, 0);
    if (lfd < 0) { perror("socket"); return 1; }

    struct sockaddr_un addr = {0};
    addr.sun_family = AF_UNIX;
    strncpy(addr.sun_path, path, sizeof(addr.sun_path) - 1);

    if (bind(lfd, (struct sockaddr*) &addr, sizeof(addr)) != 0) {
        perror("bind"); return 1;
    }
    chmod(path, S_IRUSR | S_IWUSR);
    if (listen(lfd, 8) != 0) { perror("listen"); return 1; }

    signal(SIGINT,  on_signal);
    signal(SIGTERM, on_signal);
    signal(SIGPIPE, SIG_IGN);

    fprintf(stderr, "wire_test_server: listening on %s\n", path);

    while (!g_stop) {
        int cfd = accept4(lfd, NULL, NULL, SOCK_CLOEXEC);
        if (cfd < 0) { if (errno == EINTR) continue; perror("accept"); break; }
        handle_client(cfd);
    }

    close(lfd);
    unlink(path);
    return 0;
}
