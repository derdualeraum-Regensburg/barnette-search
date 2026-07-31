/*
 * Windows build shim for Brinkmann's planar_draw.c.
 *
 * The source includes <sys/times.h> but does not use any declaration from
 * it.  MinGW-w64 does not ship that POSIX header, so this intentionally empty
 * header lets the unmodified external source compile on Windows.
 */
