import importlib.util
import unittest
from pathlib import Path

P = Path(__file__).resolve().parents[1] / 'updater_runtime.py'

class RuntimeTests(unittest.TestCase):
    def runtime(self):
        self.assertTrue(P.exists(), 'trusted runtime helper missing')
        spec = importlib.util.spec_from_file_location('runtime', P)
        assert spec and spec.loader
        mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
        return mod

    def test_exec_args(self):
        m = self.runtime()
        b, c = m.BIN, m.CONFIG
        for flag in ('-config', '--config'):
            for args in (f'{flag} {c}', f'{flag}={c}'):
                value = f'{{ path={b} ; argv[]={b} {args} -debug ; ignore_errors=no ; }}'
                self.assertEqual(m.validate_exec(value)[-1], '-debug')
        for args in (f'-config {c} --config={c}', '-config /wrong', f'-config {c} -config={c}'):
            with self.assertRaises((ValueError, OSError)):
                m.validate_exec(f'{{ path={b} ; argv[]={b} {args} ; ignore_errors=no ; }}')
        with self.assertRaises((ValueError, OSError)):
            m.validate_exec(f'{{ path=/bin/sh ; argv[]=/bin/sh {b} -config {c} ; ignore_errors=no ; }}')

    def test_changed_effective_auth_dir_refused(self):
        from unittest.mock import patch
        m = self.runtime()
        with patch.object(m, 'approved_auth', return_value='/approved/a'), patch.object(m, 'current_auth', return_value='/effective/b'):
            with self.assertRaisesRegex(ValueError, 'auth-dir changed'):
                m.verify_auth()
        with patch.object(m, 'approved_auth', return_value='/approved/a'), patch.object(m, 'current_auth', return_value='/approved/a'):
            m.verify_auth()

    def test_snapshot_rejects_links_and_budget(self):
        import tempfile, os, tarfile
        m = self.runtime()
        with tempfile.TemporaryDirectory(prefix='cpa-runtime-') as d:
            source = Path(d) / 'source'; source.mkdir()
            (source / 'ok').write_text('payload')
            out = Path(d) / 'out.tar'
            with tarfile.open(out, 'w') as archive:
                m.archive_sources(archive, [('auth', str(source))])
            (source / 'link').symlink_to('ok')
            with tarfile.open(out, 'w') as archive, self.assertRaises((ValueError, OSError)):
                m.archive_sources(archive, [('auth', str(source))])
            (source / 'link').unlink()
            os.link(source / 'ok', source / 'hard')
            with tarfile.open(out, 'w') as archive, self.assertRaises((ValueError, OSError)):
                m.archive_sources(archive, [('auth', str(source))])
            (source / 'hard').unlink()
            setattr(m, 'MAX_BYTES', 1)
            with tarfile.open(out, 'w') as archive, self.assertRaises((ValueError, OSError)):
                m.archive_sources(archive, [('auth', str(source))])

if __name__ == '__main__': unittest.main()
