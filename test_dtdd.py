import pytest
from dtdd import parse_timeline_html

@pytest.fixture
def normal_timeline_html():
    return """
    <div class="triggerRow">
        <div class="verifiedTimecode">
            <span class="verifiedYesText">Topic 1</span>
            <div class="verifiedDescriptionContainer trigger">
                <span class="verifiedTimecode">0:01:23</span>
                <span class="verifiedCommentComment">A description</span>
            </div>
            <div class="verifiedDescriptionContainer safe">
                <span class="verifiedTimecode">0:02:34</span>
            </div>
        </div>
    </div>
    """

@pytest.fixture
def missing_timecodes_html():
    return """
    <div class="triggerRow">
        <span class="verifiedYesText">Topic 2</span>
        <div class="verifiedDescriptionContainer trigger">
            <span class="verifiedCommentComment">No timecode here</span>
        </div>
    </div>
    """

@pytest.fixture
def malformed_html():
    return """
    <div class="triggerRow">
        <div class="verifiedTimecode">
            <span class="verifiedYesText">Topic 3</span>
            <div class="verifiedDescriptionContainer trigger">
                <span class="verifiedTimecode">0:10:00
            </div>
        </div>
    </div>
    """

@pytest.fixture
def hours_html():
    return """
    <div class="triggerRow">
        <div class="verifiedTimecode">
            <span class="verifiedYesText">Long Movie Topic</span>
            <div class="verifiedDescriptionContainer trigger">
                <span class="verifiedTimecode">1:23:45</span>
            </div>
        </div>
    </div>
    """

def test_parse_timeline_html_normal(normal_timeline_html):
    entries = parse_timeline_html(normal_timeline_html)
    assert len(entries) == 1
    assert entries[0] == {
        "topic": "Topic 1",
        "start": "0:01:23",
        "end": "0:02:34",
        "description": "A description"
    }

def test_parse_timeline_html_missing_timecodes(missing_timecodes_html):
    # no verifiedTimecode in row -> skips
    entries = parse_timeline_html(missing_timecodes_html)
    assert len(entries) == 0

def test_parse_timeline_html_malformed(malformed_html):
    # Malformed HTML but the regex might catch something if it matches.
    # We want to make sure it doesn't crash.
    entries = parse_timeline_html(malformed_html)
    # The regex doesn't match the closing span properly, so start is None.
    # We just ensure it handled the malformed HTML gracefully without crashing
    assert len(entries) == 1
    assert entries[0]["topic"] == "Topic 3"

def test_parse_timeline_html_hours(hours_html):
    entries = parse_timeline_html(hours_html)
    assert len(entries) == 1
    assert entries[0] == {
        "topic": "Long Movie Topic",
        "start": "1:23:45",
        "end": None,
        "description": ""
    }
