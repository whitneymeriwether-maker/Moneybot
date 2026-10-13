from pathlib import Path

def test_dashboard_reads_paper_engine():
    text = Path('app.py').read_text()
    assert 'PaperEngine' in text
    assert 'submit_order' not in text
