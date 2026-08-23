CFLAGS ?= -O2 -Wall
LDFLAGS ?=

all: rss_sampler gl_shim.so

rss_sampler: rss_sampler.c
	$(CC) $(CFLAGS) -o $@ $<

gl_shim.so: gl_shim.c
	$(CC) $(CFLAGS) -fPIC -shared -o $@ $< -ldl

clean:
	rm -f rss_sampler gl_shim.so

.PHONY: all clean
