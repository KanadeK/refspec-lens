import json
import subprocess
import sys
import tempfile
from pathlib import Path

with tempfile.TemporaryDirectory(prefix='refspec-lens-demo-') as tmp:
    root = Path(tmp)
    remote, local = root / 'remote.txt', root / 'local.txt'
    # These object IDs are synthetic; the offline tool does not read Git objects.
    remote.write_text('a' * 40 + ' refs/heads/main\n' + 'b' * 40 + ' refs/heads/private/demo\n')
    local.write_text('c' * 40 + ' refs/remotes/origin/retired\n')
    result = subprocess.run([sys.executable, '-m', 'refspec_lens', '--remote', str(remote),
                             '--local', str(local), '--refspec',
                             '+refs/heads/*:refs/remotes/origin/*', '--refspec',
                             '^refs/heads/private/*', '--prune', '--json'],
                            capture_output=True, text=True)
    assert result.returncode == 1, result.stdout + result.stderr
    report = json.loads(result.stdout)
    assert report['prune_candidates'] == ['refs/remotes/origin/retired']
    assert report['sources'][1]['state'] == 'excluded'
    print('PASS: main maps to origin/main; private/demo is excluded; retired is exposed to pruning.')
    print('Inputs were inspected offline; no Git command or ref mutation was performed.')
