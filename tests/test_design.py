"""Navigation continuity and honest progress in the redesigned workspace."""
from html.parser import HTMLParser
from urllib.parse import parse_qs, urlsplit

from web.handlers import Viewer
from web.render import layout, video_tile


class Links(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.links = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        if tag == 'a':
            self.links.append(dict(attrs))


def test_navigation_keeps_the_selected_corpus_and_list():
    html = layout('Learn', "<div id='reading-top'></div>", source='subtitle+transcript',
                  wordlist='my & words')
    for link in Links(html).links:
        url = urlsplit(link['href'])
        if url.path.startswith('/'):
            assert parse_qs(url.query) == {'src': ['subtitle+transcript'], 'list': ['my & words']}
    assert html.count('app.js?v=') == 1
    assert "class='more-nav'" in html
    assert "<summary>" in html


def test_empty_home_does_not_offer_a_missing_learning_target():
    html = layout('Learn', "<h1>No videos yet</h1>")
    assert 'Continue learning' not in html
    assert "id='main-content'" in html


def test_account_pages_have_no_learning_menu_and_one_script():
    html = layout('Sign in', '<h1>Sign in</h1>', bare=True)
    assert "class='auth-page'" in html
    assert 'Main navigation' not in html
    assert 'Quick navigation' not in html
    assert html.count('app.js?v=') == 1


def test_existing_player_script_is_not_loaded_twice():
    html = layout('Video', "<script src='/static/app.js?v=existing'></script>")
    assert html.count('app.js?v=') == 1


def test_progress_uses_the_current_corpus_denominator():
    html = Viewer._progress(30, 120)
    assert "value='30' max='120'" in html
    assert '25% of this corpus' in html
    assert '<progress' not in Viewer._progress(30, 0)
    assert '100% of this corpus' in Viewer._progress(200, 120)


def test_video_cards_escape_titles_and_preserve_the_destination():
    row = {'video': 'abc12345678', 'title': '<script>bad</script>',
           'comprehension': .87, 'minutes': 8, 'teaches': 12, 'level_label': 'A2'}
    html = video_tile(row, '/video?id=abc12345678&src=subtitle&list=travel')
    assert '<script>' not in html
    assert '&lt;script&gt;' in html
    assert '87% of words familiar' in html
    assert '8 min' in html
    assert parse_qs(urlsplit(Links(html).links[0]['href']).query)['list'] == ['travel']


def test_catalogue_cards_and_search_keep_the_collection():
    from pathlib import Path
    from types import SimpleNamespace
    viewer = Viewer.__new__(Viewer)
    viewer.app = SimpleNamespace(settings=SimpleNamespace(goal_words=Path('travel.txt')))
    viewer.source = lambda query: 'subtitle'
    viewer.ordering = lambda query: 'watch'
    viewer._plan_for = lambda *args: {}
    rows = [dict(video='abc12345678', title='An everyday conversation', comprehension=.8,
                 level=1.0, watch=.7, teaches=12, lines=100, minutes=8, **{'i+1': 30})]
    viewer._watchable = lambda *args, **kwargs: rows
    viewer._wrote_it = lambda *args: ''
    viewer._order_switch = lambda *args: ''
    viewer._add_video_form = lambda *args: ''
    viewer._page = lambda title, body, *args: body
    html = viewer.subtitles({})
    assert "class='video-grid'" in html
    assert "class='catalogue-details'" in html
    assert "name='list' value='travel'" in html
    assert '80% of words familiar' in html
    tile = next(a for a in Links(html).links if a.get('class') == 'video-tile')
    assert parse_qs(urlsplit(tile['href']).query)['list'] == ['travel']
