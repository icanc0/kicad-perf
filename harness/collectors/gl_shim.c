/*
 * gl_shim — LD_PRELOAD shim that counts GL draw/upload/swap calls.
 *
 * Overrides:
 *   glDrawArrays, glDrawElements, glDrawElementsBaseVertex,
 *   glDrawArraysInstanced, glDrawElementsInstanced,
 *   glDispatchCompute,
 *   glBufferData, glBufferSubData,
 *   glXSwapBuffers, eglSwapBuffers.
 *
 * Each override resolves the real symbol via dlsym(RTLD_NEXT, ...),
 * increments a counter, and forwards. On process exit, dumps a JSON
 * blob to $KI_GL_SHIM_OUT (or /tmp/gl_shim.json if unset).
 *
 * Build:
 *   cc -O2 -Wall -fPIC -shared -o gl_shim.so gl_shim.c -ldl
 *
 * Use:
 *   LD_PRELOAD=./gl_shim.so KI_GL_SHIM_OUT=/tmp/foo.json <app>
 */

#define _GNU_SOURCE
#include <dlfcn.h>
#include <inttypes.h>
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* Counters — atomics so multi-threaded GL apps don't corrupt them. */
static _Atomic uint64_t c_draw_arrays          = 0;
static _Atomic uint64_t c_draw_elements        = 0;
static _Atomic uint64_t c_draw_arrays_inst     = 0;
static _Atomic uint64_t c_draw_elements_inst   = 0;
static _Atomic uint64_t c_dispatch_compute     = 0;
static _Atomic uint64_t c_buffer_data          = 0;
static _Atomic uint64_t c_buffer_subdata       = 0;
static _Atomic uint64_t bytes_bufferdata       = 0;
static _Atomic uint64_t bytes_buffersubdata    = 0;
static _Atomic uint64_t total_vertices         = 0;
static _Atomic uint64_t c_swap                 = 0;

/* Resolve real symbol from the next object in the search order. */
#define REAL_SYM(name, sig) \
    typedef sig; \
    static name##_t real_##name = NULL; \
    if (!real_##name) real_##name = (name##_t)dlsym(RTLD_NEXT, #name)

/* ---------- glDrawArrays --------------------------------------- */
void glDrawArrays(unsigned mode, int first, int count) {
    REAL_SYM(glDrawArrays, void (*glDrawArrays_t)(unsigned, int, int));
    atomic_fetch_add(&c_draw_arrays, 1);
    atomic_fetch_add(&total_vertices, (uint64_t)(count > 0 ? count : 0));
    if (real_glDrawArrays) real_glDrawArrays(mode, first, count);
}

/* ---------- glDrawElements ------------------------------------- */
void glDrawElements(unsigned mode, int count, unsigned type, const void *ind) {
    REAL_SYM(glDrawElements,
             void (*glDrawElements_t)(unsigned, int, unsigned, const void *));
    atomic_fetch_add(&c_draw_elements, 1);
    atomic_fetch_add(&total_vertices, (uint64_t)(count > 0 ? count : 0));
    if (real_glDrawElements) real_glDrawElements(mode, count, type, ind);
}

/* ---------- glDrawArraysInstanced ------------------------------ */
void glDrawArraysInstanced(unsigned mode, int first, int count, int inst) {
    REAL_SYM(glDrawArraysInstanced,
             void (*glDrawArraysInstanced_t)(unsigned, int, int, int));
    atomic_fetch_add(&c_draw_arrays_inst, 1);
    atomic_fetch_add(&total_vertices, (uint64_t)(count > 0 ? count : 0)
                                    * (uint64_t)(inst > 0 ? inst : 1));
    if (real_glDrawArraysInstanced) real_glDrawArraysInstanced(mode, first, count, inst);
}

/* ---------- glDrawElementsInstanced ---------------------------- */
void glDrawElementsInstanced(unsigned mode, int count, unsigned type,
                             const void *ind, int inst) {
    REAL_SYM(glDrawElementsInstanced,
             void (*glDrawElementsInstanced_t)(unsigned, int, unsigned,
                                               const void *, int));
    atomic_fetch_add(&c_draw_elements_inst, 1);
    atomic_fetch_add(&total_vertices, (uint64_t)(count > 0 ? count : 0)
                                    * (uint64_t)(inst > 0 ? inst : 1));
    if (real_glDrawElementsInstanced)
        real_glDrawElementsInstanced(mode, count, type, ind, inst);
}

/* ---------- glDispatchCompute ---------------------------------- */
void glDispatchCompute(unsigned x, unsigned y, unsigned z) {
    REAL_SYM(glDispatchCompute,
             void (*glDispatchCompute_t)(unsigned, unsigned, unsigned));
    atomic_fetch_add(&c_dispatch_compute, 1);
    if (real_glDispatchCompute) real_glDispatchCompute(x, y, z);
}

/* ---------- glBufferData --------------------------------------- */
void glBufferData(unsigned target, long size, const void *data, unsigned usage) {
    REAL_SYM(glBufferData,
             void (*glBufferData_t)(unsigned, long, const void *, unsigned));
    atomic_fetch_add(&c_buffer_data, 1);
    if (size > 0) atomic_fetch_add(&bytes_bufferdata, (uint64_t)size);
    if (real_glBufferData) real_glBufferData(target, size, data, usage);
}

/* ---------- glBufferSubData ------------------------------------ */
void glBufferSubData(unsigned target, long off, long size, const void *data) {
    REAL_SYM(glBufferSubData,
             void (*glBufferSubData_t)(unsigned, long, long, const void *));
    atomic_fetch_add(&c_buffer_subdata, 1);
    if (size > 0) atomic_fetch_add(&bytes_buffersubdata, (uint64_t)size);
    if (real_glBufferSubData) real_glBufferSubData(target, off, size, data);
}

/* ---------- glXSwapBuffers ------------------------------------- */
void glXSwapBuffers(void *dpy, unsigned long drawable) {
    REAL_SYM(glXSwapBuffers, void (*glXSwapBuffers_t)(void *, unsigned long));
    atomic_fetch_add(&c_swap, 1);
    if (real_glXSwapBuffers) real_glXSwapBuffers(dpy, drawable);
}

/* ---------- eglSwapBuffers ------------------------------------- */
unsigned eglSwapBuffers(void *dpy, void *surface) {
    REAL_SYM(eglSwapBuffers, unsigned (*eglSwapBuffers_t)(void *, void *));
    atomic_fetch_add(&c_swap, 1);
    if (real_eglSwapBuffers) return real_eglSwapBuffers(dpy, surface);
    return 1;
}

/* ---------- Dump on exit --------------------------------------- */
__attribute__((destructor))
static void dump_counters(void) {
    const char *out = getenv("KI_GL_SHIM_OUT");
    if (!out || !*out) out = "/tmp/gl_shim.json";
    FILE *f = fopen(out, "w");
    if (!f) return;
    fprintf(f,
            "{\n"
            "  \"draw_arrays\":          %" PRIu64 ",\n"
            "  \"draw_elements\":        %" PRIu64 ",\n"
            "  \"draw_arrays_inst\":     %" PRIu64 ",\n"
            "  \"draw_elements_inst\":   %" PRIu64 ",\n"
            "  \"dispatch_compute\":     %" PRIu64 ",\n"
            "  \"draw_total\":           %" PRIu64 ",\n"
            "  \"vertices\":             %" PRIu64 ",\n"
            "  \"buffer_data\":          %" PRIu64 ",\n"
            "  \"buffer_subdata\":       %" PRIu64 ",\n"
            "  \"bytes_bufferdata\":     %" PRIu64 ",\n"
            "  \"bytes_buffersubdata\":  %" PRIu64 ",\n"
            "  \"frames\":               %" PRIu64 "\n"
            "}\n",
            atomic_load(&c_draw_arrays),
            atomic_load(&c_draw_elements),
            atomic_load(&c_draw_arrays_inst),
            atomic_load(&c_draw_elements_inst),
            atomic_load(&c_dispatch_compute),
            atomic_load(&c_draw_arrays)
              + atomic_load(&c_draw_elements)
              + atomic_load(&c_draw_arrays_inst)
              + atomic_load(&c_draw_elements_inst),
            atomic_load(&total_vertices),
            atomic_load(&c_buffer_data),
            atomic_load(&c_buffer_subdata),
            atomic_load(&bytes_bufferdata),
            atomic_load(&bytes_buffersubdata),
            atomic_load(&c_swap));
    fclose(f);
}
