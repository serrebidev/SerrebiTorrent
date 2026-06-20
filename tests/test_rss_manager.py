
import pytest
import sys
import os
import json
from unittest.mock import MagicMock, patch, mock_open

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from rss_manager import RSSManager

@pytest.fixture
def rss_manager():
    with patch('rss_manager.get_data_dir', return_value='.'):
        with patch('os.path.exists', return_value=False):
            manager = RSSManager()
            # Disable auto-saving during test setup if desired, or mock save
            manager.save = MagicMock()
            return manager

def test_downloaded_dedup(rss_manager):
    url = "http://feed.com/rss"
    rss_manager.add_feed(url)
    uid = "http://test.com/a.torrent"

    # Unknown uid is not yet downloaded
    assert rss_manager.is_downloaded(url, uid) is False
    # After marking, it is remembered (so the next poll skips it)
    rss_manager.mark_downloaded(url, uid)
    assert rss_manager.is_downloaded(url, uid) is True
    # Empty/None uids are ignored, not crashed on
    assert rss_manager.is_downloaded(url, "") is False
    rss_manager.mark_downloaded(url, None)
    # Unknown feed never reports downloaded
    assert rss_manager.is_downloaded("http://other/rss", uid) is False

def test_downloaded_list_is_bounded(rss_manager):
    url = "http://feed.com/rss"
    rss_manager.add_feed(url)
    for i in range(1200):
        rss_manager.mark_downloaded(url, f"uid-{i}")
    seen = rss_manager.feeds[url]['downloaded']
    assert len(seen) == 1000
    # Most recent retained, oldest evicted
    assert "uid-1199" in seen
    assert "uid-0" not in seen

def test_add_remove_feed(rss_manager):
    assert rss_manager.add_feed("http://test.com/rss", "Test Feed") is True
    assert "http://test.com/rss" in rss_manager.feeds
    assert rss_manager.feeds["http://test.com/rss"]['alias'] == "Test Feed"
    
    # Duplicate add
    assert rss_manager.add_feed("http://test.com/rss") is False
    
    rss_manager.remove_feed("http://test.com/rss")
    assert "http://test.com/rss" not in rss_manager.feeds

def test_add_rule(rss_manager):
    rss_manager.add_rule("test.*", "accept")
    assert len(rss_manager.rules) == 1
    assert rss_manager.rules[0]['pattern'] == "test.*"
    assert rss_manager.rules[0]['type'] == "accept"

def test_get_matches(rss_manager):
    rss_manager.add_rule("Linux", "accept")
    rss_manager.add_rule("Windows", "reject")
    
    articles = [
        {'title': 'Linux Distro ISO', 'link': 'link1'},
        {'title': 'Windows ISO', 'link': 'link2'},
        {'title': 'MacOS ISO', 'link': 'link3'}
    ]
    
    matches = rss_manager.get_matches(articles)
    assert len(matches) == 1
    assert matches[0]['title'] == 'Linux Distro ISO'

def test_get_matches_with_scope(rss_manager):
    rss_manager.add_rule("Common", "accept", scope=["feed1"])
    
    articles = [{'title': 'Common Thing', 'link': 'l'}]
    
    # Match for feed1
    assert len(rss_manager.get_matches(articles, feed_url="feed1")) == 1
    
    # No match for feed2 (rule not applicable)
    assert len(rss_manager.get_matches(articles, feed_url="feed2")) == 0

@patch('requests.get')
def test_fetch_feed(mock_get, rss_manager):
    rss_content = """
    <rss version="2.0">
    <channel>
        <item>
            <title>Test Torrent</title>
            <link>http://test.com/torrent.torrent</link>
        </item>
    </channel>
    </rss>
    """
    mock_get.return_value.status_code = 200
    mock_get.return_value.content = rss_content.encode('utf-8')
    # fetch_feed streams the body with a size cap, so feed iter_content the bytes.
    mock_get.return_value.iter_content = lambda chunk_size=8192: iter([rss_content.encode('utf-8')])

    rss_manager.add_feed("http://feed.com")
    articles = rss_manager.fetch_feed("http://feed.com")
    
    assert len(articles) == 1
    assert articles[0]['title'] == "Test Torrent"
    assert articles[0]['link'] == "http://test.com/torrent.torrent"
    
    # Check if feed updated
    assert len(rss_manager.feeds["http://feed.com"]['articles']) == 1


def test_fetch_feed_rejects_non_http_scheme(rss_manager):
    assert rss_manager.fetch_feed("file:///C:/secret.xml") == []
