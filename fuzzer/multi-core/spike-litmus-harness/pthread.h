#ifndef _FAKE_PTHREAD_H
#define _FAKE_PTHREAD_H

#include <sys/types.h>

typedef void *(*_pthread_fn)(void *);

static inline int pthread_create(pthread_t *th, pthread_attr_t *attr, _pthread_fn f, void *arg) {
    (void)th; (void)attr; (void)f; (void)arg;
    return -1;
}

static inline int pthread_join(pthread_t th, void **retval) {
    (void)th; (void)retval;
    return -1;
}

#endif
