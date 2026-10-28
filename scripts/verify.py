"""Run the current account/API and browser regression suites."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import subprocess
root = Path(__file__).resolve().parents[1]
for command in ([sys.executable, '-m', 'unittest', 'discover', '-s', 'tests', '-v'], [sys.executable, 'scripts/verify_accounts.py'], [sys.executable, 'scripts/verify_refinements.py'], [sys.executable, 'scripts/verify_people.py'], [sys.executable, 'scripts/verify_shared.py'], [sys.executable, 'scripts/verify_privacy.py'], [sys.executable, 'scripts/verify_feed.py'], [sys.executable, 'scripts/verify_editing.py']):
    subprocess.run(command, cwd=root, check=True)
