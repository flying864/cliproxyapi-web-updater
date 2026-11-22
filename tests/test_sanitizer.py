#!/usr/bin/env python3
"""Bounded malformed-input smoke fuzz under ASan/UBSan; no production paths."""
from pathlib import Path
import os
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parent.parent
HARNESS = r'''
#include "cpa-updater.c"
static uint32_t seed = 0x19840317;
static uint32_t random_byte(void) {
    seed ^= seed << 13; seed ^= seed >> 17; seed ^= seed << 5;
    return seed;
}
int main(void) {
    const char *valid[] = {
      "{\"Method\":\"GET\",\"Path\":\"/v0/management/plugins/cpa-updater/status\"}",
      "{\"Method\":\"POST\",\"Path\":\"/v0/management/plugins/cpa-updater/update\",\"Query\":{\"version\":[\"v8.0.56\"]}}",
      "{\"Method\":\"GET\",\"Path\":\"/panel\",\"Headers\":{\"Accept\":[\"application/json\"]}}",
      "{\"Method\":\"GET\",\"Path\":\"/v0/management/plugins/cpa-updater/backups\"}",
      "{\"Method\":\"POST\",\"Path\":\"/v0/management/plugins/cpa-updater/backups\",\"Query\":{\"page\":[\"1\"]}}",
      "{\"Method\":\"POST\",\"Path\":\"/v0/management/plugins/cpa-updater/cleanup\",\"Query\":{\"preview\":[\"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\"],\"ids\":[\"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb\"]}}"
    };
    for (size_t i = 0; i < 12000; i++) {
        size_t n;
        unsigned char *data;
        if (i % 2) {
            const char *source = valid[i % 6];
            n = strlen(source);
            data = malloc(n);
            if (!data) return 2;
            memcpy(data, source, n);
            for (size_t m = 0; m < i % 7; m++) data[random_byte() % n] = random_byte() % 128;
            if (i % 5 == 0) n = random_byte() % n;
        } else {
            n = random_byte() % 512;
            data = malloc(n ? n : 1);
            if (!data) return 2;
            const char alphabet[] = "{}[],:\\\"0123456789truefalsenull MethodPathQueryversion\n\r\t";
            for (size_t k = 0; k < n; k++) data[k] = alphabet[random_byte() % (sizeof(alphabet) - 1)];
        }
        cliproxy_buffer output = {0};
        plugin_call("management.handle", data, n, &output);
        if (i % 3 == 0) unlink(REQUEST_FILE);
        free(output.ptr);
        free(data);
    }
    puts("PASS: 12000 bounded malformed ABI requests under ASan/UBSan");
    return 0;
}
'''


def main():
    if not shutil.which('gcc'):
        raise SystemExit('gcc required')
    with tempfile.TemporaryDirectory(prefix='cpa-sanitizer-') as tmp:
        temp = Path(tmp)
        (temp / 'private-state/inbox').mkdir(parents=True)
        (temp / 'private-public').mkdir(parents=True)
        (temp / 'private-public/status.json').write_text('{"protocol":1,"backups_protocol":1,"state":"ready","latest":"v8.0.56"}')
        (temp / 'private-public/status.json').chmod(0o644)
        (temp / 'private-public/backups.json').write_text('{"protocol":1,"state":"ready","token":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","items":[]}')
        (temp / 'private-public/backups.json').chmod(0o644)
        harness = temp / 'harness.c'
        harness.write_text(HARNESS)
        binary = temp / 'sanitizer-test'
        subprocess.run(['gcc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-O1', '-g',
                        '-fsanitize=address,undefined', '-fno-omit-frame-pointer',
                        '-DCPA_TEST', '-DCPA_RUN="' + str(temp / 'private-state') + '"',
                        '-DCPA_PUBLIC="' + str(temp / 'private-public') + '"',
                        '-DCPA_STATUS_UID=' + str(os.getuid()), '-I', str(ROOT), str(harness), '-o', str(binary)],
                       check=True, timeout=30)
        subprocess.run([str(binary)], check=True, timeout=45)


if __name__ == '__main__':
    main()
