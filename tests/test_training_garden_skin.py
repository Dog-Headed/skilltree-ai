"""Training login and shell reuse the garden skin without dropping DOM contracts."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / 'app' / 'static'
LEAF = 'viewBox="0 0 22 26"'
# Order matters: botanical tokens must exist before training.css aliases them.
ASSETS = ('/assets/fonts.css', '/assets/botanical.css', '/assets/controls.css', '/assets/training.css')


def _page(name):
    return (STATIC / name).read_text(encoding='utf-8')


def test_training_pages_load_garden_assets_and_leaf_brand():
    login, shell = _page('training-login.html'), _page('training.html')
    for page in (login, shell):
        assert 'data-theme="light"' in page
        assert 'data-subject="general"' in page
        assert LEAF in page and 'var(--leaf-deep)' in page and 'var(--stem)' in page
        assert '✳' not in page
        cursor = 0
        for asset in ASSETS:
            found = page.find(asset)
            assert found > cursor, asset
            cursor = found
    for asset in ASSETS:
        assert (STATIC / asset.rsplit('/', 1)[-1]).is_file()


def test_training_login_keeps_form_contract():
    page = _page('training-login.html')
    for ident in (
        'login-form', 'account', 'password', 'confirm-field', 'confirm-password', 'remember',
        'login-error', 'login-submit', 'auth-mode', 'login-title', 'login-lead', 'login-note',
        'guest-entry',
    ):
        assert f'id="{ident}"' in page
    assert 'id="login-tree"' in page and 'class="growth-graph login-tree"' in page
    assert '/assets/training-login-botanical.png' in page
    growth = page.find('/assets/botanical.js')
    replay = page.find('/assets/training-growth.js')
    form = page.find('/assets/training-login.js')
    assert 0 < growth < replay < form
    script = _page('training-growth.js')
    assert 'SkillTreeBotanical' in script
    assert 'a-draw' in script and 'a-sprout' in script and 'a-unfurl' in script
    assert 'prefers-reduced-motion' in script


def test_training_shell_keeps_dom_contract():
    page = _page('training.html')
    for ident in ('content', 'navigation', 'unit-name', 'identity', 'switch-account', 'logout', 'loading'):
        assert f'id="{ident}"' in page
    assert 'class="shell"' in page and 'class="rail"' in page and 'class="unit-label"' in page
    assert 'class="seed-dot"' in page and 'class="workspace"' in page
    # training.js relabels unaffiliated sessions via footer.firstChild.
    assert '<footer>SkillTree' in page
    assert '/assets/training.js' in page


def test_training_phone_layout_scrolls_nav_inside_the_page():
    css = _page('training.css')
    phone = css.split('@media(max-width:740px)', 1)[1].split('@media', 1)[0]
    assert 'overflow-x:clip' in phone
    assert 'flex-wrap:nowrap' in phone and 'min-width:0' in phone
    assert '.hero-mark{display:none}' in phone
    assert 'grid-template-columns:1fr}' in phone or '.cards{grid-template-columns:1fr}' in phone
    assert '.members{grid-template-columns:1fr}' in phone
    assert 'width:100%' in css.split('.material-form input:not', 1)[1][:180]
    source = _page('training.js')
    assert "scrollIntoView({block:'nearest',inline:'nearest'})" in source


def test_training_css_inherits_garden_tokens():
    css = _page('training.css')
    assert '--ink:#' not in css and '--paper:#' not in css and '--muted:#' not in css and '--line:#' not in css
    assert '--green:var(--leaf-deep)' in css
    assert 'SkillTree Design' not in css
    assert 'var(--font-body)' in css and 'var(--font-display)' in css
    assert css.count('{') == css.count('}')


def test_training_hero_uses_leaf_not_asterisk():
    source = _page('training.js')
    assert 'hero-mark' in source and LEAF in source and 'var(--leaf-deep)' in source
    assert '✳' not in source
    assert '用这份资料准备课程' in source
    for icon in ('training-icon-free-learn.png', 'training-icon-upload.png', 'training-icon-tasks.png'):
        assert '/assets/' + icon in source
        assert (STATIC / icon).is_file()


def test_training_illustrations_are_served_and_pages_are_not(tmp_path):
    from fastapi.testclient import TestClient
    from app.v3.learning_api import create_learning_app
    from app.v3.runtime_storage import initialize_learning_storage
    from app.v3.storage import V3Paths, initialize_storage
    paths = initialize_learning_storage(initialize_storage(V3Paths(tmp_path)))
    client = TestClient(create_learning_app(
        paths, legacy_business_path=tmp_path / 'missing-v2.sqlite', legacy_checkpoint_path=tmp_path / 'missing-cp.sqlite'))
    for name in (
        'training-login-botanical.png', 'training-icon-free-learn.png',
        'training-icon-upload.png', 'training-icon-tasks.png', 'botanical.js', 'training-growth.js',
    ):
        response = client.get('/assets/' + name)
        assert response.status_code == 200, name
        if name.endswith('.png'):
            assert response.headers['content-type'].startswith('image/png')
    for blocked in ('login.html', 'training-login.html', 'v3.html', 'training.html'):
        assert client.get('/assets/' + blocked).status_code == 404
