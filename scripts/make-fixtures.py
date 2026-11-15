"""Generate clearly synthetic PDFs for local browser QA, not the clinical dataset."""
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
from tests.test_workflow import make_pdf

folder = root / 'tmp' / 'fixtures'
folder.mkdir(parents=True, exist_ok=True)
for role in ('Protocol', 'SAP'):
    (folder / f'{role}.pdf').write_bytes(make_pdf(role))
print('Created synthetic Protocol/SAP fixtures in tmp/fixtures.')
